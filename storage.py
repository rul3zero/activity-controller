"""Local preferences, notes, and a per-user single-instance lock for Paper."""

from dataclasses import asdict
import fcntl
import json
import logging
import os
from pathlib import Path
from threading import RLock


class AppStorage:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.environ.get(
            "PAPER_DATA_DIR", str(Path.home() / "Library/Application Support/Paper")
        ))
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def read_config(self) -> dict:
        try:
            data = json.loads((self.root / "settings.json").read_text())
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logging.getLogger(__name__).warning("Could not load saved settings; using defaults")
            return {}

    def _write(self, name: str, text: str):
        with self._lock:
            temporary = self.root / (name + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(self.root / name)

    def save_config(self, config):
        data = asdict(config)
        # A command-line preview must not silently affect the next launch.
        data.pop("dry_run", None)
        self._write("settings.json", json.dumps(data, indent=2))

    def read_note(self) -> str:
        with self._lock:
            try:
                return (self.root / "note.txt").read_text(encoding="utf-8")
            except FileNotFoundError:
                return ""

    def save_note(self, text: str):
        self._write("note.txt", text)


class InstanceLock:
    """Keep one app per user; the OS releases the lock even after a crash."""

    def __init__(self, storage: AppStorage):
        self.file = (storage.root / "instance.json").open("a+", encoding="utf-8")

    def acquire(self) -> bool:
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def url(self) -> str | None:
        self.file.seek(0)
        try:
            value = json.load(self.file).get("url", "")
            from urllib.parse import urlparse
            parsed = urlparse(value)
            if parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port:
                return value
        except (ValueError, AttributeError):
            pass
        return None

    def publish(self, url: str):
        self.file.seek(0)
        self.file.truncate()
        json.dump({"url": url, "pid": os.getpid()}, self.file)
        self.file.flush()

    def close(self):
        self.file.close()
