"""OS-owned lock: two Clara processes cannot drive the same saved workspace."""
import os
from contextlib import contextmanager


@contextmanager
def single_instance(data):
    path = data / "instance.lock"
    handle = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("Clara is already running for this data folder. Use clara open.") from error
        yield
    finally:
        handle.close()
