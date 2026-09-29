from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# The two scopes this project needs, and nothing more:
#   gmail.modify -> read, label, archive (remove INBOX), trash (add TRASH).
#                  It does NOT allow permanent delete — we don't want that.
#   gmail.labels -> create/manage our own labels.
# A scope you don't request, you don't get. Don't add extras.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

# Where we cache the day pass + membership card so we don't re-consent
# every run. This file is gitignored.
TOKEN = Path("token.json")


def get_credentials() -> Credentials:
    """Return valid credentials, doing the least work needed to get them.

    The mental model (three states):
      - A short-lived ACCESS token (the "day pass") expires ~hourly.
      - A long-lived REFRESH token (the "membership card") lets us trade
        for a new day pass silently.
      - Both are cached in TOKEN. Our job is to always return a valid
        day pass, taking the cheapest route.
    """
    creds = None

    # 1. If we already have a token file, load creds from it.
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)

    # 2. If we have nothing, or what we have isn't valid, we need to act.
    if not creds or not creds.valid:
        # 3a. But if we DO have creds and they're merely expired, and we
        #     hold a refresh token, trade it for a new access token.
        #     No human/browser needed. This is the autonomous path.
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        # 3b. Otherwise (no token file, or no refresh token) we must do the
        #     full OAuth dance: open a browser, human clicks Allow.
        #     Only happens the first time (or after a refresh token dies).
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # 4. Persist whichever creds we ended up with, so next run starts
        #    from the cache. (MUST write both tokens, not just access.)
        TOKEN.write_text(creds.to_json())

    # 5. Valid creds (either loaded, refreshed, or freshly consented).
    return creds


if __name__ == "__main__":
    creds = get_credentials()
    # The one check that matters: a real refresh token means we can run
    # unattended. "MISSING" means Google reused an old consent — fix by
    # revoking the app at myaccount.google.com/permissions, deleting
    # token.json, and running again.
    print("refresh_token:", "OK" if creds.refresh_token else "MISSING")
    print("expiry:", creds.expiry)
