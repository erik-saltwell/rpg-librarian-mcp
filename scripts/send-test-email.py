"""Send one diagnostic email using the application's configuration and transport.

Run from the checkout with: .venv/bin/python scripts/send-test-email.py
"""

from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from rpg_librarian.config import load_env
from rpg_librarian.imports.config import setting
from rpg_librarian.smtp import send_message


def main() -> int:
    env_path = load_env()
    message = EmailMessage()
    message["From"] = setting("SMTP_USERNAME")
    message["To"] = setting("REVIEW_EMAIL_TO")
    message["Subject"] = "RPG Librarian: email configuration test"
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="rpg-librarian.local")
    message.set_content(
        "This is a requested email configuration test from RPG Librarian.\n\n"
        "It uses the same SMTP configuration and transport as process-batch and "
        "sync-sources. No catalog processing was performed.\n"
    )
    print(f"Configuration: {env_path or 'existing environment'}")
    print(f"From: {message['From']}")
    print(f"To: {message['To']}")
    print(f"Message-ID: {message['Message-ID']}", flush=True)
    try:
        send_message(message)
    except Exception as error:
        # Do not print server responses or credentials in diagnostic output.
        print(f"SMTP submission failed: {type(error).__name__}")
        return 1
    print("SMTP accepted the test email. Check the receiving mailbox for delivery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
