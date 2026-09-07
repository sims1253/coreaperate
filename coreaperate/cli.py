import argparse
import asyncio
import json
import secrets
from pathlib import Path
from .model import loads, dumps, project, require
from .spool import atomic_new, Spool
from .store import Store
from .network import Coordinator, client
from .lock import instance_lock


def main():
    p = argparse.ArgumentParser(description="Experimental MIDI companion. Use disposable copies only.")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="generate two private participant configs and host credentials")
    init.add_argument("--directory", required=True)
    init.add_argument("--url", default="ws://127.0.0.1:8765")
    host = sub.add_parser("host", help="run authoritative server (participate with join in another terminal)")
    host.add_argument("--baseline", required=True)
    host.add_argument("--credentials", required=True)
    host.add_argument("--database", required=True)
    host.add_argument("--bind", default="127.0.0.1")
    host.add_argument("--port", type=int, default=8765)
    join = sub.add_parser("join")
    join.add_argument("--config", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("left"); compare.add_argument("right")
    args = p.parse_args()
    if args.command == "init":
        root = Path(args.directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
        credentials = {"A": secrets.token_urlsafe(32), "B": secrets.token_urlsafe(32)}
        atomic_new(root / "credentials.local.json", dumps(credentials).encode())
        for actor, token in credentials.items():
            ipc = root / actor
            Spool(ipc, "to_bridge"); Spool(ipc, "from_bridge")
            (ipc / "recovery").mkdir(exist_ok=True)
            config = dict(client=actor, token=token, url=args.url, ipc=str(ipc))
            atomic_new(root / f"{actor}.local.json", dumps(config).encode())
            # This local file has no secrets and is read as data by the bridge.
            atomic_new(ipc / "bridge.json", dumps(dict(client=actor, ipc=str(ipc))).encode())
        print("Created private configuration in", root, "— do not share the whole directory.")
    elif args.command == "host":
        baseline = project(loads(Path(args.baseline).read_bytes()))
        credentials = loads(Path(args.credentials).read_bytes())
        require(type(credentials) is dict and len(credentials) == 2 and all(isinstance(v,str) and len(v)>=32 for v in credentials.values()), "exactly two credentials required")
        db_path = Path(args.database).resolve()
        with instance_lock(db_path.parent, db_path.name + ".lock"):
            store = Store(db_path, baseline)
            print(f"Experimental unencrypted WebSocket server on {args.bind}:{args.port}. Trusted private network only.")
            asyncio.run(Coordinator(store, credentials).run(args.bind, args.port))
    elif args.command == "join":
        config = loads(Path(args.config).read_bytes())
        root = Path(config["ipc"]).resolve()
        config["ipc"] = str(root)
        Spool(root, "from_bridge"); Spool(root, "to_bridge")
        (root / "recovery").mkdir(exist_ok=True)
        public = dict(client=config["client"], ipc=str(root))
        if not (root / "bridge.json").exists():
            atomic_new(root / "bridge.json", dumps(public).encode())
        else:
            require(loads((root / "bridge.json").read_bytes()) == public, "IPC configuration belongs to another client")
        with instance_lock(config["ipc"]):
            asyncio.run(client(config))
    else:
        a, b = (loads(Path(x).read_bytes()) for x in (args.left, args.right))
        a = a.get("current", a); b = b.get("current", b)
        require(a == b, "musical states differ")
        print("Canonical musical states are equal.")


if __name__ == "__main__":
    main()
