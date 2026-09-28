"""Cross-process serialization for SUMO compilers sharing native logs and caches."""
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import tempfile
import threading

_thread_lock = threading.Lock()


@contextmanager
def acquire():
    if not _thread_lock.acquire(blocking=False):
        raise BlockingIOError("A SUMO compiler operation is already running")
    try:
        path = Path(tempfile.gettempdir()) / "sumo24-mcp-compiler.lock"
        with path.open("a+b") as lock:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        _thread_lock.release()


def serialized(function):
    @wraps(function)
    def run(*args, **kwargs):
        try:
            with acquire():
                return function(*args, **kwargs)
        except (BlockingIOError, PermissionError) as exc:
            return {"ok": False, "stage": "busy", "reason": "Compiler lock unavailable: " + str(exc)}
    return run
