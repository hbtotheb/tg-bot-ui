from __future__ import annotations

import logging
import time

from typing import Optional

try:
    from bot.core.whitelist import is_whitelisted
except ImportError:
    from core.whitelist import is_whitelisted

logger = logging.getLogger(__name__)


class InquiryRateLimiter:
    """Specialized rate limiter for inquiry wizard interactions and 1-shot LLM submissions."""

    def __init__(
        self,
        action_cooldown: float = 0.25,
        submission_cooldown: float = 3.0,
        max_daily_submissions: int = 10,
    ) -> None:
        self.action_cooldown = action_cooldown
        self.submission_cooldown = submission_cooldown
        self.max_daily_submissions = max_daily_submissions

        self._last_action_time: dict[int, float] = {}
        self._last_submission_time: dict[int, float] = {}
        self._daily_submissions: dict[int, list[float]] = {}

    def is_action_limited(self, user_id: int, username: Optional[str] = None) -> bool:
        """Check if user is tapping wizard buttons too quickly (debouncing). Whitelisted users bypass."""
        if is_whitelisted(user_id, username):
            return False
        now = time.time()
        last = self._last_action_time.get(user_id, 0.0)
        if now - last < self.action_cooldown:
            return True
        self._last_action_time[user_id] = now

        # Prune memory if growing large
        if len(self._last_action_time) > 10000:
            self._last_action_time = {k: v for k, v in self._last_action_time.items() if now - v < 60}
        return False

    def is_submission_limited(self, user_id: int, username: Optional[str] = None) -> tuple[bool, str | None]:
        """
        Check if user is allowed to submit a new requirement synthesis.
        Enforces both cooldown and daily rolling cap. Whitelisted users bypass.
        """
        if is_whitelisted(user_id, username):
            return False, None

        now = time.time()

        # 1. Burst / Submission Cooldown
        last_sub = self._last_submission_time.get(user_id, 0.0)
        if now - last_sub < self.submission_cooldown:
            remaining = int(self.submission_cooldown - (now - last_sub))
            return True, f"Please wait {remaining}s before generating another inquiry."

        # 2. Daily Rolling Quota (24 hours)
        history = self._daily_submissions.get(user_id, [])
        valid_history = [t for t in history if now - t < 86400]
        self._daily_submissions[user_id] = valid_history

        if len(valid_history) >= self.max_daily_submissions:
            return True, f"Daily inquiry limit reached ({self.max_daily_submissions}/day). You can contact teachers directly."

        return False, None

    def record_submission(self, user_id: int) -> None:
        """Record successful 1-shot LLM synthesis submission timestamp."""
        now = time.time()
        self._last_submission_time[user_id] = now
        self._daily_submissions.setdefault(user_id, []).append(now)


inquiry_rate_limiter = InquiryRateLimiter()
