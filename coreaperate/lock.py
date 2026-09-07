"""OS-released local companion lock; no stale PID-file stealing."""
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def instance_lock(root, name="companion.lock"):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b"0"); f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
