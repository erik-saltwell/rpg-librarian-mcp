"""Private, atomic run receipts retained beside the catalog."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Run:
    @classmethod
    def load(cls, path: Path) -> Run:
        """Reopen a receipt to retry known failed delivery without rerunning stages."""
        run = cls.__new__(cls)
        run.path = path
        run.directory = path.parent
        run.data = json.loads(path.read_text())
        return run

    def __init__(self, catalog: Path, root: Path):
        run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:12]}"
        self.directory = catalog.parent / "logs" / "process-batch" / run_id
        self.directory.mkdir(parents=True, mode=0o700)
        self.path = self.directory / "summary.json"
        self.data: dict[str, Any] = {
            "version": 1,
            "run_id": run_id,
            "catalog": str(catalog),
            "root": str(root),
            "pid": os.getpid(),
            "started_at": now(),
            "finished_at": None,
            "outcome": "running",
            "new_input": None,
            "inventory": None,
            "stages": [],
            "backlog": None,
            "notification": {"status": "not_evaluated"},
        }
        self.save()

    def save(self) -> None:
        write_json(self.path, self.data)

    def recover_abandoned(self) -> None:
        from .processes import stop_abandoned

        for path in self.directory.parent.glob("*/summary.json"):
            if path == self.path:
                continue
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if record.get("catalog") != self.data["catalog"]:
                continue
            if record.get("finished_at") is None:
                stop_abandoned(record["run_id"])
                record.update(outcome="interrupted", finished_at=now())
                record["recovered_by"] = self.data["run_id"]
                notification = record.get("notification", {})
                if notification.get("status") == "pending":
                    record["notification"] = {
                        **notification,
                        "status": "unknown",
                        "reason": "delivery_interrupted",
                    }
                elif notification.get("status") == "not_evaluated":
                    record["notification"] = {
                        "status": "skipped",
                        "reason": "parent_interrupted",
                    }
                for stage in record.get("stages", []):
                    if stage.get("outcome") == "running":
                        stage.update(outcome="interrupted", finished_at=now())
                write_json(path, record)
