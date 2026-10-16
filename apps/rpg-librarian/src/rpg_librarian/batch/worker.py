"""Internal stage subprocess; writes structured results without scraping CLI text."""

from __future__ import annotations

import json
import signal
import sys
import traceback
from pathlib import Path

from ..observability import CallTracker, configure_wide_event_logs
from ..progress import configure
from .records import write_json


def interrupted(signum, frame) -> None:
    raise KeyboardInterrupt


def has_issues(name: str, metrics: dict) -> bool:
    if name == "scan":
        return bool(metrics.get("errored") or metrics.get("unreachable_roots"))
    if name == "find-packs":
        return any(
            metrics.get(k) for k in ("errors", "search_errors", "not_asked", "stopped")
        )
    if name == "enrich":
        return any(
            value.get("errors")
            or value.get("stopped_reason")
            or value.get("skipped_reason")
            for value in metrics.get("sources", {}).values()
        )
    if name == "reorganize":
        return any(
            metrics.get(k)
            for k in ("blocked", "errors", "not_attempted", "unreachable")
        )
    if name == "filing":
        return bool(metrics.get("remaining"))
    if name == "quick-dedupe":
        return bool(metrics.get("errors") or metrics.get("move_errors"))
    return False


def main() -> int:
    from ..__main__ import _HANDLERS, build_parser
    from .filing import file_catalog

    signal.signal(signal.SIGTERM, interrupted)
    request_path = Path(sys.argv[1])
    result_path = request_path.with_name(request_path.stem + "-result.json")
    request = json.loads(request_path.read_text())
    if request.get("progress"):
        configure(Path(request["progress"]))
    catalog = Path(request["catalog"])
    name = request["name"]
    configure_wide_event_logs(catalog)
    result = {"name": name, "outcome": "failed", "metrics": {}}
    try:
        with CallTracker(name, "batch", arguments={"catalog": str(catalog)}) as tracker:
            if name == "filing":
                metrics = file_catalog(
                    catalog, request_path.parent, source=request.get("source")
                )
                tracker.fields.update(metrics)
                code = 0
            else:
                args = build_parser().parse_args(request["arguments"])
                if name == "quick-dedupe":
                    args.batch_mode = True
                code = _HANDLERS[name](args, catalog)
            result.update(metrics=tracker.fields, returncode=code)
            result["outcome"] = (
                "failed"
                if code
                else "issues"
                if has_issues(name, tracker.fields)
                else "completed"
            )
    except KeyboardInterrupt:
        result["error_type"] = "Interrupted"
        write_json(result_path, result)
        return 130
    except Exception as error:
        result["error_type"] = type(error).__name__
        traceback.print_exc()
        write_json(result_path, result)
        return 1
    write_json(result_path, result)
    return code


if __name__ == "__main__":
    sys.exit(main())
