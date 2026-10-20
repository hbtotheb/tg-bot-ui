from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
WHITELIST_FILE = ROOT / "constants" / "whitelist.json"

# In-memory mapping from user_id -> username for resolution when only user_id is provided
_user_id_to_username: dict[int, str] = {}


def record_user_identity(user_id: int, username: str | None) -> None:
    """Record known user_id -> username mapping for dynamic whitelist resolution."""
    if username:
        clean = username.strip().lstrip("@").lower()
        if clean:
            _user_id_to_username[user_id] = clean


def get_whitelisted_user_ids() -> Set[int]:
    """
    Parses and returns the set of whitelisted user IDs from environment variables,
    admin configuration, and optional constants/whitelist.json.
    """
    user_ids: Set[int] = set()

    # 1. Admins are automatically whitelisted
    try:
        from core.admin import get_admin_user_ids
    except ImportError:
        try:
            from bot.core.admin import get_admin_user_ids
        except ImportError:
            get_admin_user_ids = lambda: set()

    user_ids.update(get_admin_user_ids())

    # 2. Environment variables (supports IDs and mixed lists)
    raw_env = [
        os.getenv("RATE_LIMIT_WHITELIST", ""),
        os.getenv("INTERNAL_USERS", ""),
        os.getenv("WHITELIST_USERS", ""),
        os.getenv("WHITELIST_USER_IDS", ""),
        os.getenv("INTERNAL_USER_IDS", ""),
    ]
    for raw in raw_env:
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned.isdigit() or (cleaned.startswith("-") and cleaned[1:].isdigit()):
                try:
                    user_ids.add(int(cleaned))
                except ValueError:
                    pass

    # 3. Optional constants/whitelist.json
    if WHITELIST_FILE.is_file():
        try:
            with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    ids = data.get("user_ids") or data.get("ids") or []
                    for i in ids:
                        if isinstance(i, int):
                            user_ids.add(i)
                        elif isinstance(i, str) and (i.isdigit() or (i.startswith("-") and i[1:].isdigit())):
                            user_ids.add(int(i))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, int):
                            user_ids.add(item)
                        elif isinstance(item, str) and (item.isdigit() or (item.startswith("-") and item[1:].isdigit())):
                            user_ids.add(int(item))
        except Exception as e:
            logger.warning("Failed to parse %s: %s", WHITELIST_FILE, e)

    return user_ids


def get_whitelisted_usernames() -> Set[str]:
    """
    Parses and returns the set of whitelisted usernames (lowercase, without leading @)
    from environment variables and optional constants/whitelist.json.
    """
    usernames: Set[str] = set()

    # 1. Environment variables
    raw_env = [
        os.getenv("RATE_LIMIT_WHITELIST", ""),
        os.getenv("INTERNAL_USERS", ""),
        os.getenv("WHITELIST_USERS", ""),
        os.getenv("WHITELIST_USERNAMES", ""),
        os.getenv("INTERNAL_USERNAMES", ""),
    ]
    for raw in raw_env:
        for part in raw.split(","):
            cleaned = part.strip().lstrip("@").lower()
            if cleaned and not cleaned.isdigit() and not (cleaned.startswith("-") and cleaned[1:].isdigit()):
                usernames.add(cleaned)

    # 2. Optional constants/whitelist.json
    if WHITELIST_FILE.is_file():
        try:
            with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    names = data.get("usernames") or data.get("users") or []
                    for n in names:
                        if isinstance(n, str):
                            clean = n.strip().lstrip("@").lower()
                            if clean and not clean.isdigit() and not (clean.startswith("-") and clean[1:].isdigit()):
                                usernames.add(clean)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            clean = item.strip().lstrip("@").lower()
                            if clean and not clean.isdigit() and not (clean.startswith("-") and clean[1:].isdigit()):
                                usernames.add(clean)
        except Exception as e:
            logger.warning("Failed to parse %s: %s", WHITELIST_FILE, e)

    return usernames


def is_whitelisted(user_id: Optional[int] = None, username: Optional[str] = None) -> bool:
    """
    Check if a user is whitelisted to bypass rate limits.
    Can be verified by numeric Telegram user_id, Telegram username, or both.
    """
    if username:
        record_user_identity(user_id or 0, username)
        clean = username.strip().lstrip("@").lower()
        if clean in get_whitelisted_usernames():
            return True

    if user_id is not None:
        if user_id in get_whitelisted_user_ids():
            return True
        # Check if known username for this user_id is whitelisted
        recorded_name = _user_id_to_username.get(user_id)
        if recorded_name and recorded_name in get_whitelisted_usernames():
            return True

    return False
