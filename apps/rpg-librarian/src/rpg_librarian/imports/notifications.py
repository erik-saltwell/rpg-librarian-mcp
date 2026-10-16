"""Nonempty review digests with a durable outbox and semantic delivery identities."""

from __future__ import annotations

import json
import os
import uuid
from email.message import EmailMessage
from pathlib import Path

from ..smtp import send_message
from .config import setting
from .state import State


def export_reviews(state: State) -> Path:
    rows = [
        dict(r)
        for r in state.db.execute(
            "SELECT "
            "subject,reason,lifecycle,updated_at FROM"
            " review WHERE"
            " resolved=0 ORDER BY subject"
        )
    ]
    path = state.directory / "brendan-reviews.json"
    path.write_text(json.dumps(rows, indent=2) + "\n")
    os.chmod(path, 0o600)
    return path


def notify(state: State, *, enabled: bool = True) -> int:
    report = export_reviews(state)
    if not enabled:
        return 0
    rows = [dict(r) for r in state.db.execute("SELECT * FROM review WHERE resolved=0")]
    members = {
        r["subject"]: f"{r['lifecycle']}:{r['fingerprint']}"
        for r in rows
        if r["delivered"] != f"{r['lifecycle']}:{r['fingerprint']}"
    }
    if not members:
        return 0
    pending = state.db.execute(
        "SELECT * FROM digest WHERE status='pending' ORDER BY id LIMIT 1"
    ).fetchone()
    if pending and json.loads(pending["members"]) == members:
        identity, message_id = pending["id"], pending["message_id"]
    else:
        state.db.execute("UPDATE digest SET status='superseded' WHERE status='pending'")
        message_id = f"<rpg-brendan-{uuid.uuid4()}@rpg-librarian.local>"
        result = state.db.execute(
            "INSERT INTO digest(message_id,members) VALUES(?,?)",
            (message_id, json.dumps(members, sort_keys=True)),
        )
        identity = result.lastrowid
        state.db.commit()
    try:
        message = EmailMessage()
        message["From"] = setting("SMTP_USERNAME")
        message["To"] = setting("REVIEW_EMAIL_TO")
        message["Subject"] = f"RPG Librarian: {len(members)} Brendan import review(s)"
        message["Message-ID"] = message_id
        message.set_content(
            "These items need your review:\n\n"
            + "\n\n".join(
                f"{r['subject']}: {r['reason']}"
                for r in rows
                if r["subject"] in members
            )
            + f"\n\nFull unresolved review list on this machine: {report}\n"
        )
        send_message(message)
        with state.db:
            state.db.execute(
                "UPDATE digest SET status='sent',error=NULL WHERE id=?", (identity,)
            )
            for subject, version in members.items():
                state.db.execute(
                    "UPDATE review SET delivered=? WHERE subject=?", (version, subject)
                )
        print(f"Sent review digest for {len(members)} item(s).", flush=True)
        return len(members)
    except Exception as error:
        state.db.execute(
            "UPDATE digest SET error=? WHERE id=?", (type(error).__name__, identity)
        )
        state.db.commit()
        raise RuntimeError(
            "Review email failed; the digest remains queued. Check SMTP configuration."
        ) from None
