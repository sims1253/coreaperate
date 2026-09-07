import asyncio
import contextlib
import hmac
import time
import uuid
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from .model import dumps, loads, require, keys, ident, digest, LIMIT, Invalid
from .spool import Spool


class Coordinator:
    def __init__(self, store, credentials):
        self.store, self.credentials = store, credentials
        self.peers = {}
        self.delivery_lock = asyncio.Lock()

    async def presence(self):
        msg = dumps(dict(type="presence", peers=sorted(self.peers)))
        for peer in list(self.peers.values()):
            with contextlib.suppress(ConnectionClosed):
                await peer.send(msg)

    async def handler(self, ws):
        actor = None
        try:
            hello = loads(await asyncio.wait_for(ws.recv(), 10))
            keys(hello, "type protocol client token session baseline")
            require(hello["type"] == "hello" and hello["protocol"] == 1, "protocol mismatch")
            candidate = ident(hello["client"])
            require(candidate in self.credentials and isinstance(hello["token"], str) and
                    hmac.compare_digest(hello["token"], self.credentials[candidate]), "authentication failed")
            require(candidate not in self.peers, "client already connected; use distinct identities")
            require(hello["session"] == self.store.state["project"]["session"], "wrong prepared session")
            require(hello["baseline"] == self.store.state["baseline"], "incompatible baseline; use copies of the same prepared project")
            actor = candidate
            self.peers[actor] = ws
            await ws.send(dumps(self.store.snapshot()))
            await self.presence()
            async for raw in ws:
                msg = loads(raw)
                require(type(msg) is dict, "message must be an object")
                if msg.get("type") == "replay":
                    keys(msg, "type after")
                    for ev in self.store.replay(msg["after"]):
                        await ws.send(dumps(ev))
                elif msg.get("type") == "snapshot_request":
                    keys(msg, "type")
                    await ws.send(dumps(self.store.snapshot()))
                elif msg.get("type") == "ack":
                    keys(msg, "type seq")
                    require(type(msg["seq"]) is int and 0 <= msg["seq"] <= self.store.state["seq"], "invalid acknowledgement")
                    # History retained in full; ack is a delivery watermark, never permission to compact.
                elif msg.get("type") == "outcome_request":
                    keys(msg, "type operation")
                    await ws.send(dumps(self.store.outcome(actor, msg["operation"])))
                else:
                    if msg.get("type") == "handover":
                        require(msg.get("payload", {}).get("owner") in self.credentials, "handover needs registered peer")
                    async with self.delivery_lock:
                        outcome, fresh = self.store.propose(actor, msg)
                        targets = list(self.peers.values()) if fresh else [ws]
                        for peer in targets:
                            with contextlib.suppress(ConnectionClosed):
                                await peer.send(dumps(outcome))
        except (Invalid, ValueError, TypeError, KeyError, asyncio.TimeoutError) as exc:
            with contextlib.suppress(ConnectionClosed):
                reason = str(exc) if isinstance(exc, Invalid) else "Malformed request or handshake timeout"
                await ws.send(dumps(dict(type="fatal", reason=reason + ". Check private config and use the same prepared baseline.")))
                await ws.close(code=1008)
        except ConnectionClosed:
            pass
        finally:
            if actor is not None:
                self.peers.pop(actor, None)
                await self.presence()

    async def run(self, bind, port):
        async with serve(self.handler, bind, port, max_size=LIMIT, max_queue=16, compression=None):
            await asyncio.Future()


async def client(config):
    """Durable relay. A bridge hello starts an explicitly reconciled connection."""
    incoming = Spool(config["ipc"], "to_bridge")
    outgoing = Spool(config["ipc"], "from_bridge")
    print("Waiting for REAPER bridge. IPC:", config["ipc"])
    while True:
        hello = None
        for id_, msg in outgoing.pending():
            if msg.get("type") == "bridge_hello":
                if hello is None:
                    hello = (id_, msg)
            elif "protocol" not in msg:
                outgoing.ack(id_)  # obsolete controls from a closed connection
        if hello is None:
            await asyncio.sleep(.1)
            continue
        try:
            old_proposals = {id_ for id_, msg in outgoing.pending() if "protocol" in msg}
            async with connect(config["url"], max_size=LIMIT, max_queue=16, compression=None, proxy=None) as ws:
                await ws.send(dumps(dict(type="hello", protocol=1, client=config["client"], token=config["token"],
                                        session=hello[1]["baseline"]["session"], baseline=digest(hello[1]["baseline"]))))
                initial = loads(await ws.recv())
                incoming.send(initial)
                outgoing.ack(hello[0])
                if initial["type"] != "snapshot":
                    continue
                sent = set()
                ready = False
                last_pulse = 0
                while True:
                    if time.monotonic() - last_pulse > 1:
                        incoming.send(dict(type="connection", connected=True, client=config["client"], time=int(time.time())))
                        last_pulse = time.monotonic()
                    for id_, msg in outgoing.pending():
                        if id_ in sent:
                            continue
                        if msg.get("type") == "bridge_hello":
                            raise Invalid("bridge requested reconciliation")
                        if msg.get("type") == "disconnect":
                            outgoing.ack(id_)
                            raise Invalid("paused by bridge")
                        if msg.get("type") == "ready":
                            ready = True
                            outgoing.ack(id_)
                            continue
                        if id_ in old_proposals:
                            await ws.send(dumps(dict(type="outcome_request", operation=msg)))
                        elif "protocol" in msg and not ready:
                            continue
                        else:
                            await ws.send(dumps(msg))
                        if "protocol" in msg:
                            sent.add(id_)  # receipt only after coordinator outcome is safely in inbound spool
                        else:
                            outgoing.ack(id_)
                    try:
                        msg = loads(await asyncio.wait_for(ws.recv(), .05))
                    except asyncio.TimeoutError:
                        continue
                    incoming.send(msg)
                    if msg.get("type") in ("event", "rejected"):
                        for id_, proposal in outgoing.pending():
                            if proposal.get("id") == msg.get("id"):
                                outgoing.ack(id_)
        except (OSError, ConnectionClosed, Invalid, asyncio.TimeoutError):
            try:
                incoming.send(dict(type="connection", connected=False, reason="Disconnected. Local edits preserved. Export/reconcile and press Connect."))
            except (OSError, Invalid):
                print("Cannot write bridge status: IPC unavailable/full. Publication stopped; preserve local data, repair IPC, then reconnect.")
            # Never automatically reconnect an offline branch. New bridge hello required.
            outgoing.ack(hello[0])
