"""Application configuration from environment variables."""

import os
from typing import Dict, List


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean from environment variable."""
    return os.getenv(name, str(default)).lower() in ("true", "1", "yes")


def _parse_remotes(raw: str) -> List[Dict[str, str]]:
    """Parse 'NAME:URL,NAME:URL' into [{"name": ..., "url": ...}, ...]."""
    if not raw:
        return []
    remotes = []
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        name, url = entry.split(":", 1)
        remotes.append({"name": name.strip(), "url": url.strip().rstrip("/")})
    return remotes


# Feature flags
INTELLIGENT_RETRY_ENABLED = _env_bool("INTELLIGENT_RETRY_ENABLED", False)
MULTIPLE_ENVIRONMENTS = _env_bool("MULTIPLE_ENVIRONMENTS", False)

# Remote environments for test case promotion
CHECKMATE_REMOTES = _parse_remotes(os.getenv("CHECKMATE_REMOTES", ""))
CHECKMATE_API_KEY = os.getenv("CHECKMATE_API_KEY", "")
