"""One producer per direction. Immutable messages and durable receiver receipts."""
import os
import uuid
import time
from pathlib import Path
from .model import dumps, loads, ident, require, LIMIT


def atomic_new(path, data):
    path = Path(path)
    require(not path.exists(), "refusing to overwrite immutable file")
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    # UUID filenames + single producer eliminate destination races. Never os.replace.
    os.rename(tmp, path)


class Spool:
    def __init__(self, root, direction, capacity=64):
        self.path = Path(root) / direction
        self.path.mkdir(parents=True, exist_ok=True)
        self.capacity = capacity

    def send(self, message, id_=None):
        self.collect()
        require(len(list(self.path.glob("*.json"))) < self.capacity, "IPC queue full; synchronization paused")
        id_ = ident(id_ or (str(time.time_ns()) + '_' + uuid.uuid4().hex))
        raw = dumps(message).encode()
        require(len(raw) <= LIMIT, "IPC message too large")
        path = self.path / (id_ + ".json")
        if path.exists():
            require(path.read_bytes() == raw, "IPC ID conflict")
        elif not path.with_suffix(".ack").exists():
            atomic_new(path, raw)
        return id_

    def pending(self):
        for path in sorted(self.path.glob("*.json"))[:self.capacity]:
            if not path.with_suffix(".ack").exists():
                require(path.stat().st_size <= LIMIT, "oversized IPC file")
                yield path.stem, loads(path.read_bytes())

    def ack(self, id_):
        path = self.path / (ident(id_) + ".ack")
        if not path.exists():
            atomic_new(path, b"applied\n")

    def collect(self):
        for path in self.path.glob("*.json"):
            if path.with_suffix(".ack").exists():
                path.unlink()  # reader has closed it and durably acknowledged
        # Receipts retained indefinitely for dedup; no destructive backup cleanup.
