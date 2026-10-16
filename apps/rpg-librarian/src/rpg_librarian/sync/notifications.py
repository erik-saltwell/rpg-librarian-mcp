"""Manual admission notices and one combined end-of-run failure message."""

from __future__ import annotations

import hashlib
import json
from email.message import EmailMessage

from ..imports.config import setting
from ..imports.state import State
from ..smtp import send_message


def message(subject: str, identifier: str, text: str) -> EmailMessage:
    mail = EmailMessage()
    mail["From"] = setting("SMTP_USERNAME")
    mail["To"] = setting("REVIEW_EMAIL_TO")
    mail["Subject"] = subject
    mail["Message-ID"] = f"<rpg-sync-{identifier}@rpg-librarian.local>"
    mail.set_content(text)
    return mail


def manual_required(
    state: State, name: str, items: list, limit: int, result: dict, receipt: str, save
) -> bool:
    manifest = [{"identity": i.identity, "version": i.version} for i in items]
    fingerprint = hashlib.sha256(
        json.dumps([manifest, limit], sort_keys=True).encode()
    ).hexdigest()
    previous = state.get("sync_manual_notice", {})
    if previous.get("fingerprint") == fingerprint and previous.get("status") in {
        "sent",
        "pending",
        "unknown",
    }:
        result["notification"] = {
            "status": "skipped",
            "reason": "unchanged_manual_batch",
            "previous_status": previous["status"],
        }
        save()
        return True
    notice = {"fingerprint": fingerprint, "status": "pending"}
    state.set("sync_manual_notice", notice)
    state.db.commit()
    result["notification"] = notice.copy()
    save()
    try:
        mail = message(
            f"RPG Librarian: {name} needs manual import ({len(items)} files)",
            f"manual-{name}-{fingerprint[:24]}",
            f"Source: {name}\nFiles not already owned: {len(items)}\n"
            f"Automatic limit: {limit}\n\n"
            "Copy and process this entire batch manually. Nothing was published "
            "to the inbox and processing was not started.\n\n"
            f"Local manifest and run summary: {receipt}\n",
        )
        send_message(mail)
        notice["status"] = "sent"
    except Exception as error:
        notice.update(status="failed", error_type=type(error).__name__)
    state.set("sync_manual_notice", notice)
    state.db.commit()
    result["notification"] = notice.copy()
    save()
    return notice["status"] == "sent"


def failures(run: dict, receipt: str, save) -> bool:
    failed = [r for r in run["sources"] if r["outcome"] == "failed"]
    if not failed:
        run["notification"] = {"status": "skipped", "reason": "no_failures"}
        save()
        return True
    run["notification"] = {"status": "pending"}
    save()
    try:
        lines = [f"Catalog: {run['catalog']}", f"Failed sources: {len(failed)}", ""]
        for result in failed:
            lines.append(
                f"- {result['name']}: "
                f"{result.get('error', result.get('error_type', 'Failed'))}"
            )
            if result.get("batch_summary"):
                lines.append(f"  Processing summary: {result['batch_summary']}")
                if result.get("backlog") is not None:
                    lines.append(
                        f"  Total catalog review backlog: {result['backlog']['total']}"
                    )
        lines.extend(
            [
                "",
                "Completed work is preserved. Resolve the reported problem "
                "and rerun sync-sources; unfinished admitted batches resume "
                "automatically.",
                "",
                f"Local sync summary: {receipt}",
            ]
        )
        send_message(
            message(
                f"RPG Librarian: source sync failed ({len(failed)} source(s))",
                run["run_id"],
                "\n".join(lines) + "\n",
            )
        )
        run["notification"] = {"status": "sent"}
    except Exception as error:
        run["notification"] = {"status": "failed", "error_type": type(error).__name__}
    save()
    return run["notification"]["status"] == "sent"
