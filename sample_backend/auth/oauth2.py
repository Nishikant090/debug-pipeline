"""OAuth2 'Sign in with Google' flow."""
import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"


class OAuthError(Exception):
    pass


def exchange_code(code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict:
    """Swap an OAuth2 authorization code for access and ID tokens.

    Codes are single-use and expire after a few minutes. The frontend retries this
    call on any network error, so when a slow first attempt actually succeeded, the
    retry reuses the same code and fails with invalid_grant.
    """
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": client_id, "client_secret": client_secret,
    }, timeout=10)
    if resp.status_code == 400 and resp.json().get("error") == "invalid_grant":
        raise OAuthError("Authorization code has expired or already been used")
    resp.raise_for_status()
    return resp.json()
