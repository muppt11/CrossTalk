"""GitHub OAuth sign-in (web flow + PKCE) with server-side, in-memory sessions.

The OAuth token never leaves the server: the browser only ever holds an opaque random
session id in an HttpOnly cookie.
"""

import base64
import hashlib
import logging
import secrets
import threading
import time
from urllib.parse import urlencode

import requests

from config import get_secret
from github_client import github_headers

logger = logging.getLogger("crosstalk.auth")

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
# GitHub offers no read-only private-repo scope for OAuth apps; "repo" is the only option.
SCOPE = "repo"

SESSION_COOKIE = "ct_session"
SESSION_TTL = 8 * 60 * 60
PENDING_TTL = 10 * 60
MAX_PENDING = 100
MAX_SESSIONS = 200
AVATAR_PREFIX = "https://avatars.githubusercontent.com/"
_PLACEHOLDERS = {"", "your-client-id", "your-client-secret"}

_lock = threading.Lock()
_pending: dict[str, dict] = {}
_sessions: dict[str, dict] = {}


class AuthError(Exception):
    """Sign-in failed; the message is safe to show to the user."""


def _credentials() -> tuple[str, str] | None:
    client_id = (get_secret("GITHUB_CLIENT_ID") or "").strip()
    client_secret = (get_secret("GITHUB_CLIENT_SECRET") or "").strip()
    if client_id.lower() in _PLACEHOLDERS or client_secret.lower() in _PLACEHOLDERS:
        return None
    return client_id, client_secret


def is_configured() -> bool:
    return _credentials() is not None


def base_url() -> str:
    return (get_secret("PUBLIC_BASE_URL") or "http://127.0.0.1:8600").rstrip("/")


def redirect_uri() -> str:
    return f"{base_url()}/auth/callback"


def cookie_secure() -> bool:
    return base_url().startswith("https://")


def _evict(store: dict[str, dict], ttl_key: str, limit: int) -> None:
    """Drop expired entries, then the oldest ones if the store is still over its cap."""
    now = time.time()
    for key in [k for k, v in store.items() if v[ttl_key] <= now]:
        del store[key]
    while len(store) >= limit:
        del store[min(store, key=lambda k: store[k][ttl_key])]


def begin_login() -> str:
    """Create a single-use state + PKCE verifier and return the GitHub authorize URL."""
    credentials = _credentials()
    if credentials is None:
        raise AuthError("GitHub sign-in isn't configured.")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    with _lock:
        _evict(_pending, "expires", MAX_PENDING)
        _pending[state] = {"verifier": verifier, "expires": time.time() + PENDING_TTL}
    query = urlencode(
        {
            "client_id": credentials[0],
            "redirect_uri": redirect_uri(),
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def complete_login(code: str, state: str) -> str:
    """Verify state, exchange the code for a token, and return a new session id."""
    with _lock:
        pending = _pending.pop(state, None)  # single use: a replayed state finds nothing
    if pending is None or pending["expires"] <= time.time():
        raise AuthError("Sign-in expired or was not started here. Try again.")
    credentials = _credentials()
    if credentials is None:
        raise AuthError("GitHub sign-in isn't configured.")

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": credentials[0],
                "client_secret": credentials[1],
                "code": code,
                "redirect_uri": redirect_uri(),
                "code_verifier": pending["verifier"],
            },
            headers={"Accept": "application/json", "User-Agent": "CrossTalk-MVP"},
            timeout=15,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        logger.warning("GitHub token exchange failed: %s", type(error).__name__)
        raise AuthError("Could not complete sign-in with GitHub.") from None

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if response.status_code != 200 or not isinstance(token, str) or not token:
        logger.warning("GitHub token exchange rejected: %s", payload.get("error") if isinstance(payload, dict) else "bad response")
        raise AuthError("GitHub did not accept the sign-in.")

    try:
        user_response = requests.get(USER_URL, headers=github_headers("application/vnd.github+json", token), timeout=15)
        user_response.raise_for_status()
        user = user_response.json()
        login = user["login"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        logger.warning("GitHub user lookup failed: %s", type(error).__name__)
        raise AuthError("Signed in, but could not read your GitHub profile.") from None

    avatar_url = user.get("avatar_url") if isinstance(user.get("avatar_url"), str) else ""
    session_id = secrets.token_urlsafe(32)
    with _lock:
        _evict(_sessions, "expires", MAX_SESSIONS)
        _sessions[session_id] = {
            "token": token,
            "login": str(login),
            "avatar_url": avatar_url if avatar_url.startswith(AVATAR_PREFIX) else "",
            "expires": time.time() + SESSION_TTL,
        }
    return session_id


def get_session(session_id: str | None) -> dict | None:
    if not session_id:
        return None
    with _lock:
        session = _sessions.get(session_id)
        if session is None:
            return None
        if session["expires"] <= time.time():
            del _sessions[session_id]
            return None
        return dict(session)


def end_session(session_id: str | None) -> None:
    if session_id:
        with _lock:
            _sessions.pop(session_id, None)
