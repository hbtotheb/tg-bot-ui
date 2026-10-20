from __future__ import annotations

import time
import logging

from typing import Optional

try:
    from bot.core.whitelist import is_whitelisted
except ImportError:
    from core.whitelist import is_whitelisted

logger = logging.getLogger("RateLimiter")


class UserRateLimiter:
    """Lightweight in-memory rate limiter and debouncer for user commands and inline buttons."""

    def __init__(self, callback_cooldown: float = 0.5, message_cooldown: float = 0.5):
        self.callback_cooldown = callback_cooldown
        self.message_cooldown = message_cooldown
        self._last_callback_time: dict[int, float] = {}
        self._last_message_time: dict[int, float] = {}

    def is_callback_rate_limited(self, user_id: int, username: Optional[str] = None) -> bool:
        """Check if a user is clicking callback buttons too quickly (debouncing). Whitelisted users bypass."""
        if is_whitelisted(user_id, username):
            return False
        now = time.time()
        last = self._last_callback_time.get(user_id, 0.0)
        if now - last < self.callback_cooldown:
            return True
        self._last_callback_time[user_id] = now
        if len(self._last_callback_time) > 10000:
            self._last_callback_time = {k: v for k, v in self._last_callback_time.items() if now - v < 60}
        return False

    def is_message_rate_limited(self, user_id: int, username: Optional[str] = None) -> bool:
        """Check if a user is sending search queries or commands too quickly. Whitelisted users bypass."""
        if is_whitelisted(user_id, username):
            return False
        now = time.time()
        last = self._last_message_time.get(user_id, 0.0)
        if now - last < self.message_cooldown:
            return True
        self._last_message_time[user_id] = now
        if len(self._last_message_time) > 10000:
            self._last_message_time = {k: v for k, v in self._last_message_time.items() if now - v < 60}
        return False


rate_limiter = UserRateLimiter(callback_cooldown=0.5, message_cooldown=0.5)
