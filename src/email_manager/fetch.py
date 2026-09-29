"""Layer 1 — fetch new mail and record a sync cursor.

Run this on a timer. Start read-only: list recent messages, print them, change
nothing. Verify it works before it lets it touch anything.

TODO: fill this in.
"""

from typing import Any

# TODO: import get_service from .gmail


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
    # TODO
    raise NotImplementedError


def main() -> None:
    """Print a read-only preview of recent mail. Change nothing.

    Read the arg count from sys.argv so you can pass a limit:
      uv run python -m email_manager.fetch 8
    Default to 10 if no arg.

    HINT: mark unread mail (labelIds containing "UNREAD") with a leading "*".
    """
    # TODO
    raise NotImplementedError


if __name__ == "__main__":
    main()
