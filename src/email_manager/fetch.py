"""Layer 1 — fetch new mail and record a sync cursor.

Run this on a timer. Start read-only: list recent messages, print them, change
nothing. Verify it works before it lets it touch anything.
"""

import sys
from typing import Any

from .gmail import get_service


def list_recent(max_results: int = 10) -> list[dict[str, Any]]:
    """Return metadata for the most recent messages.

    Algorithm (see analysis doc §A1 for the full picture):
      1. Ask Gmail for the ids of the most recent messages.
         (users().messages().list with userId="me" and maxResults)
      2. For each id, fetch the message metadata.
         (users().messages().get with format="metadata")
      3. Pull the From / Subject out of payload["headers"]
         (a list of {"name":..., "value":...} dicts — turn it into a dict
          keyed by name so you can look up "From" directly).
      4. Also keep labelIds and the message id.

    QUOTA (important, don't ignore): messages.list = 5 units,
    messages.get = 20 units. Budget is 6,000 units/min/user, so keep
    max_results modest. Don't fetch bodies yet.

    Return: a list of dicts with id, from, subject, labels.
    """
    service = get_service()
    # pyright can't see .users() — google-api-python-client ships no type info
    # and returns a bare Resource, so the whole chain is Unknown to it. Real
    # code, false positive.
    messages = service.users().messages()  # type: ignore[reportAttributeAccessIssue]

    # 1. Ids only — no sender, no subject comes back from this call.
    listed = messages.list(userId="me", maxResults=max_results).execute()

    out: list[dict[str, Any]] = []
    for stub in listed.get("messages", []):
        # 2. format="metadata" keeps bodies out of the response.
        msg = messages.get(userId="me", id=stub["id"], format="metadata").execute()

        # 3. headers arrives as a flat list of {"name", "value"} dicts, so
        #    fold it into a dict to get direct lookups. From and Subject sit
        #    well past the Received/ARC-Seal plumbing, so filter by name.
        headers = {
            h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])
        }

        # 4. "from" is a Python keyword, so it's only valid as a quoted key.
        out.append(
            {
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "labels": msg.get("labelIds", []),
            }
        )

    return out


def main() -> None:
    """Print a read-only preview of recent mail. Change nothing.

    Read the arg count from sys.argv so you can pass a limit:
      uv run python -m email_manager.fetch 8
    Default to 10 if no arg.
    """
    args = sys.argv[1:]
    limit = int(args[0]) if args else 10

    for msg in list_recent(limit):
        unread = "*" if "UNREAD" in msg["labels"] else " "
        raw = msg["from"]
        sender = raw.split("<")[-1].rstrip(">") if "<" in raw else raw
        print(f"{unread} {sender} — {msg['subject']}")


if __name__ == "__main__":
    main()
