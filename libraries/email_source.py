"""Fetch account-opening document attachments from a Gmail inbox via IMAP.

Looks for unread messages whose subject contains "ACCOUNT OPENING", downloads
each message's image / PDF attachments into a per-email folder under `input/`,
then marks the emails as read.

Credentials are read from Robocorp Vault under the secret name
`gmail_credentials` with keys:
    - username : the Gmail address
    - password : a Gmail App Password (NOT the account password)
"""
from pathlib import Path

from robocorp import log, vault

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993

SUBJECT_FILTER = "ACCOUNT OPENING"
VAULT_SECRET_NAME = "gmail_credentials"

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".pdf", ".tif", ".tiff")


def _safe_token(text: str, n: int = 40) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in (text or ""))
    return cleaned[:n] or "msg"


def fetch_attachments(target_dir: Path) -> list[Path]:
    """Connect, find unread ACCOUNT-OPENING emails, save attachments, mark read.

    Returns the list of saved file paths (filtered to supported extensions).
    Raises if vault credentials are missing or IMAP login fails — callers
    should decide whether to abort the run or continue with existing files.
    """
    # Lazy import so the module loads cleanly in OCR_INPUT_ONLY / dev envs
    # that don't have rpaframework installed.
    from RPA.Email.ImapSmtp import ImapSmtp

    creds = vault.get_secret(VAULT_SECRET_NAME)
    username = creds["username"]
    password = creds["password"]

    mail = ImapSmtp(imap_server=GMAIL_IMAP_HOST, imap_port=GMAIL_IMAP_PORT)
    mail.authorize_imap(account=username, password=password)
    log.info(f"Authorized to Gmail IMAP as {username}")

    try:
        messages = mail.list_messages(
            criterion=f'UNSEEN SUBJECT "{SUBJECT_FILTER}"',
            source_folder="INBOX",
        ) or []
        log.info(f"Found {len(messages)} unread '{SUBJECT_FILTER}' messages")

        if not messages:
            return []

        target_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []

        for idx, msg in enumerate(messages):
            uid = str(msg.get("uid") or msg.get("UID") or idx)
            subj = str(msg.get("Subject") or msg.get("subject") or "no-subject")
            sender = str(msg.get("From") or msg.get("from") or "")
            msg_dir = target_dir / f"{uid}_{_safe_token(subj)}"
            msg_dir.mkdir(parents=True, exist_ok=True)

            # Persist the sender alongside attachments so the orchestrator can
            # carry it into the application record without re-parsing IMAP.
            (msg_dir / "_meta.txt").write_text(
                f"uid={uid}\nfrom={sender}\nsubject={subj}\n",
                encoding="utf-8",
            )

            saved = mail.save_attachment(
                msg,
                target_folder=str(msg_dir),
                overwrite=True,
            ) or []

            entries = saved if isinstance(saved, list) else [saved]
            for entry in entries:
                if isinstance(entry, dict):
                    raw_path = entry.get("Saved-Path") or entry.get("path")
                else:
                    raw_path = entry
                if not raw_path:
                    continue
                path = Path(str(raw_path))
                if not path.is_file():
                    continue
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    log.info(f"Skipping unsupported attachment: {path.name}")
                    continue
                downloaded.append(path)

        uids = [str(m.get("uid") or m.get("UID")) for m in messages
                if m.get("uid") or m.get("UID")]
        if uids:
            try:
                mail.mark_as_read(criterion=f"UID {','.join(uids)}")
            except Exception as exc:
                log.warn(f"mark_as_read failed (continuing): {exc}")

        log.info(f"Saved {len(downloaded)} attachment(s); processed {len(messages)} email(s)")

        return downloaded
    finally:
        try:
            mail.close_connection()
        except Exception:
            pass


def read_message_meta(msg_dir: Path) -> dict:
    """Read the _meta.txt sidecar written by fetch_attachments."""
    meta_path = msg_dir / "_meta.txt"
    if not meta_path.is_file():
        return {}
    out = {}
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out
