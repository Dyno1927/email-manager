"""Gmail API client wrapper.

Builds an authorized Gmail v1 service object you can call.

TODO: fill this in.
"""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from .auth import get_credentials


def get_service() -> Resource:
    """Return an authorized Gmail v1 service.

    Steps:
      1. Get valid creds (call get_credentials() from .auth).
      2. Build a Gmail "v1" service with those creds.
      3. Return it.

    HINT: the builder takes a service name ("gmail"), a version ("v1"),
    and the credentials.
    """

    creds: Credentials = get_credentials()
    service: Resource = build(serviceName="gmail", version="v1", credentials=creds)

    return service
