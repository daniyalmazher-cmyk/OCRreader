"""Per-run audit logger. Each run gets a uuid and a chronological event list."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLogger:
    def __init__(self) -> None:
        self.run_id = str(uuid.uuid4())
        self.started_at = _now()
        self.events: list[dict] = []

    def event(self, name: str, payload: dict | None = None) -> None:
        self.events.append({
            "timestamp": _now(),
            "event": name,
            "payload": payload or {},
        })

    def flush(self, path: Path) -> None:
        record = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": _now(),
            "event_count": len(self.events),
            "events": self.events,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
