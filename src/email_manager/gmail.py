"""Gmail API client wrapper.

Builds an authorized Gmail v1 service object you can call.

TODO: fill this in.
"""

from googleapiclient.discovery import Resource

# TODO: import get_credentials from .auth


def get_service() -> Resource:
    """Return an authorized Gmail v1 service.

    Steps:
      1. Get valid creds (call get_credentials() from .auth).
      2. Build a Gmail "v1" service with those creds.
      3. Return it.

    HINT: the builder takes a service name ("gmail"), a version ("v1"),
    and the credentials.
    """
    # TODO
    raise NotImplementedError
