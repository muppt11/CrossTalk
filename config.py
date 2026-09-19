import os
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11: fall back to environment variables only
    tomllib = None

_SECRETS_FILE = Path(__file__).parent / ".streamlit" / "secrets.toml"


def get_secret(name: str) -> str | None:
    """Read a setting from the environment, then from .streamlit/secrets.toml if present."""
    value = os.getenv(name)
    if value:
        return value
    if tomllib is None or not _SECRETS_FILE.is_file():
        return None
    try:
        with _SECRETS_FILE.open("rb") as handle:
            secret = tomllib.load(handle).get(name)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return secret if isinstance(secret, str) and secret else None
