from __future__ import annotations

import os
import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)


def get_admin_user_ids() -> Set[int]:
    """Parses and returns the set of configured admin user IDs from environment variables."""
    raw = os.getenv("ADMIN_USER_IDS") or os.getenv("ADMIN_USER_ID") or os.getenv("ADMIN_IDS") or ""
    admin_ids: Set[int] = set()
    for part in raw.split(","):
        cleaned = part.strip()
        if cleaned:
            try:
                admin_ids.add(int(cleaned))
            except ValueError:
                logger.warning("Invalid admin user ID in environment: %s", cleaned)
    return admin_ids


def is_admin(user_id: Optional[int]) -> bool:
    """Checks if a given Telegram user ID has admin privileges."""
    if user_id is None:
        return False
    return user_id in get_admin_user_ids()
