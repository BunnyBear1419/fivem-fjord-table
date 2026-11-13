"""Crash-safer JSON storage helpers shared by the crafting bot."""
import copy
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_STORAGE_LOCK = threading.RLock()


@contextmanager
def file_lock():
    """Serialize this process's read/modify/write sequences."""
    with _STORAGE_LOCK:
        yield


def read_json(path: Path, default: Any):
    """Read JSON without silently replacing a corrupt file with defaults."""
    path = Path(path)
    with file_lock():
        if not path.exists():
            return copy.deepcopy(default)
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"{path.name} contains invalid JSON; the original file was preserved. "
                "Restore a known-good backup before editing this data."
            ) from exc


def atomic_write_json(path: Path, data: Any) -> Path:
    """Write JSON to a same-directory temp file, fsync, then atomically replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock():
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            try:
                directory_fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
    return path
