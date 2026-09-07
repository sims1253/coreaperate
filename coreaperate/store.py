"""Single-writer SQLite coordinator; state, history and dedup commit together."""
import copy
import sqlite3
from .model import Invalid, require, keys, ident, integer, project, dumps, loads, digest


class Store:
    def __init__(self, path, baseline):
        project(baseline)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT);
        CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, actor TEXT, fingerprint TEXT, outcome TEXT);
        CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY, event TEXT);
        CREATE TABLE IF NOT EXISTS identities (id TEXT PRIMARY KEY, track TEXT, item TEXT);
        """)
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if row:
            self.state = loads(row[0])
            require(self.state["baseline"] == digest(baseline), "database belongs to another baseline")
            for meta in self.state["meta"].values():
                meta["epoch"] += 1  # fences queued proposals from previous coordinator lifetime
        else:
            self.state = dict(project=baseline, baseline=digest(baseline), seq=0,
                              meta={k: dict(owner="", epoch=1, revision=0) for k in baseline["tracks"]})
        with self.db:
            self._save(self.state)
            self._identities(self.state["project"], register=True)

    def _save(self, state):
        self.db.execute("INSERT OR REPLACE INTO state VALUES(1,?)", (dumps(state),))

    def _identities(self, state, register=False):
        for track, value in state["tracks"].items():
            for item_id, it in value["items"].items():
                for identity in (item_id, it["take"]):
                    old = self.db.execute("SELECT track,item FROM identities WHERE id=?", (identity,)).fetchone()
                    require(old is None or old == (track, item_id), "historical identity reused or moved across tracks")
                    if register:
                        self.db.execute("INSERT OR IGNORE INTO identities VALUES(?,?,?)", (identity, track, item_id))

    def snapshot(self):
        return dict(type="snapshot", **copy.deepcopy(self.state))

    def replay(self, after):
        integer(after, 0, self.state["seq"])
        return [loads(r[0]) for r in self.db.execute("SELECT event FROM history WHERE seq>? ORDER BY seq", (after,))]

    def outcome(self, actor, op):
        ident(op["id"])
        row = self.db.execute("SELECT fingerprint,outcome FROM operations WHERE id=?", (op["id"],)).fetchone()
        if row:
            require(row[0] == digest(dict(actor=actor, operation=op)), "operation ID conflict")
            return loads(row[1])
        return dict(type="rejected", id=op["id"], reason="Unaccepted proposal from previous connection preserved as a local branch; export and reconcile.")

    def propose(self, actor, op):
        ident(actor)
        keys(op, "protocol session id track revision epoch type payload")
        ident(op["id"])
        fp = digest(dict(actor=actor, operation=op))
        old = self.db.execute("SELECT fingerprint,outcome FROM operations WHERE id=?", (op["id"],)).fetchone()
        if old:
            require(old[0] == fp, "operation ID reused with different content or actor")
            return loads(old[1]), False
        next_state = copy.deepcopy(self.state)
        try:
            require(op["protocol"] == 1 and type(op["protocol"]) is int, "protocol mismatch")
            require(op["session"] == self.state["project"]["session"], "session mismatch")
            ident(op["track"])
            require(op["track"] in next_state["meta"], "unknown track")
            m = next_state["meta"][op["track"]]
            integer(op["revision"], 0, 2**53-1); integer(op["epoch"], 1, 2**53-1)
            require(op["epoch"] == m["epoch"], "stale ownership epoch; reconcile")
            require(op["revision"] == m["revision"], "stale track revision; preserve local branch")
            t = next_state["project"]["tracks"][op["track"]]
            before = copy.deepcopy(t)
            kind, payload = op["type"], op["payload"]
            if kind == "claim":
                keys(payload, "")
                require(not m["owner"], "track already owned")
                m["owner"] = actor; m["epoch"] += 1
            else:
                require(m["owner"] == actor, "track is not owned by authenticated actor")
                if kind in ("release", "handover"):
                    keys(payload, "" if kind == "release" else "owner")
                    owner = "" if kind == "release" else ident(payload["owner"])
                    require(owner != actor, "handover needs the other peer")
                    m["owner"] = owner; m["epoch"] += 1
                elif kind == "properties":
                    keys(payload, "name volume pan")
                    t.update(payload)
                elif kind == "put_item":
                    keys(payload, "item")
                    it = payload["item"]
                    require(isinstance(it, dict) and "id" in it, "invalid item")
                    if it["id"] in t["items"]:
                        require(it["take"] == t["items"][it["id"]]["take"], "take identity changed")
                    t["items"][it["id"]] = it
                elif kind == "delete_item":
                    keys(payload, "id"); ident(payload["id"])
                    require(payload["id"] in t["items"], "missing item")
                    del t["items"][payload["id"]]
                elif kind == "undo":
                    keys(payload, "")
                    candidate = None
                    for event in reversed(self.replay(0)):
                        if event["actor"] == actor and event["kind"] in ("properties", "put_item", "delete_item"):
                            candidate = event; break
                    require(candidate is not None, "no shared edit to undo")
                    require(candidate["track"] == op["track"], "latest edit belongs to another track")
                    require(candidate["meta"]["revision"] == m["revision"] and candidate["after"] == t, "undo is stale")
                    t = copy.deepcopy(candidate["before"])
                    next_state["project"]["tracks"][op["track"]] = t
                else:
                    raise Invalid("unknown operation type")
            project(next_state["project"])
            self._identities(next_state["project"])
            m["revision"] += 1
            next_state["seq"] += 1
            outcome = dict(type="event", id=op["id"], seq=next_state["seq"], actor=actor,
                           track=op["track"], kind=kind, before=before, after=t, meta=m)
        except (Invalid, KeyError, TypeError) as exc:
            outcome = dict(type="rejected", id=op["id"], reason=str(exc))
        with self.db:
            if outcome["type"] == "event":
                self._save(next_state)
                self._identities(next_state["project"], register=True)
                self.db.execute("INSERT INTO history VALUES(?,?)", (outcome["seq"], dumps(outcome)))
            self.db.execute("INSERT INTO operations VALUES(?,?,?,?)", (op["id"], actor, fp, dumps(outcome)))
        if outcome["type"] == "event":
            self.state = next_state
        return copy.deepcopy(outcome), outcome["type"] == "event"
