"""Batch-specific quiet-run rules, independent of Brendan's digest policy."""

from __future__ import annotations

from email.message import EmailMessage

from ..imports.config import setting
from ..smtp import send_message
from .records import Run


def notify(run: Run) -> bool:
    data = run.data
    if data["new_input"] == 0:
        data["notification"] = {"status": "skipped", "reason": "no_new_input"}
        run.save()
        return True
    backlog = data["backlog"]
    if data["outcome"] == "completed" and backlog is not None and backlog["total"] == 0:
        data["notification"] = {
            "status": "skipped",
            "reason": "completed_without_reviews",
        }
        run.save()
        return True
    data["notification"] = {"status": "pending"}
    run.save()
    try:
        message = EmailMessage()
        message["From"] = setting("SMTP_USERNAME")
        message["To"] = setting("REVIEW_EMAIL_TO")
        total = str(backlog["total"]) if backlog is not None else "unknown"
        message["Subject"] = f"RPG Librarian: {data['outcome']}; {total} review item(s)"
        message["Message-ID"] = f"<rpg-batch-{data['run_id']}@rpg-librarian.local>"
        lines = [
            f"Outcome: {data['outcome']}",
            f"Catalog: {data['catalog']}",
            f"Input root: {data['root']}",
            f"New or changed input files: {data['new_input']}",
            f"Total outstanding review items: {total}",
            "",
            "Stages:",
        ]
        lines.extend(f"- {s['name']}: {s['outcome']}" for s in data["stages"])
        if data.get("error_type"):
            lines.append(
                f"Run error: {data['error_type']}; see the local summary and logs."
            )
        if backlog is not None:
            lines.extend(["", "Review categories (may overlap):"])
            lines.extend(
                f"- {key}: {value}" for key, value in backlog["counts"].items()
            )
        lines.extend(["", f"Local run summary: {run.path}"])
        message.set_content("\n".join(lines) + "\n")
        send_message(message)
        data["notification"] = {"status": "sent"}
        run.save()
        return True
    except Exception as error:
        data["notification"] = {"status": "failed", "error_type": type(error).__name__}
        run.save()
        return False
