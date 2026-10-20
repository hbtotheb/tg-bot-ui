from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class InquiryStep(str, Enum):
    """Sequential wizard steps for teacher preference matching."""
    LOOK = "look"        # #1: preferred look: young/mature/heavy makeup or custom
    BODY = "body"        # #2: preferred body type: skinny/busty/tall/petite or custom
    PRICE = "price"      # #3: preferred price range: select range
    VALUE = "value"      # #4: what you value most: service/price/face/body or custom
    MAP = "map"          # #5: map pin / geo location
    CONFIRMED = "confirmed"


@dataclass
class InquirySession:
    """In-memory state for an active requirement collection wizard session."""
    user_id: int
    chat_id: int
    teacher_id: int
    from_index: int = 0
    teacher_name: str = ""
    teacher_account: str | None = None
    teacher_city: str | None = None
    teacher_district: str | None = None
    teacher_price: str | None = None
    teacher_post_link: str | None = None
    bot_username: str = ""

    # Step state
    step: InquiryStep = InquiryStep.LOOK

    # Collected Slots
    preferred_look: str | None = None   # #1: young / mature / heavy makeup or custom text
    preferred_body: str | None = None   # #2: skinny / busty / tall / petite or custom text
    preferred_price: str | None = None  # #3: select price range (300 granularity, e.g. 600以下(1P), 600-900(1P), etc.)
    value_most: str | None = None       # #4: service / price / face / body or custom text
    latitude: float | None = None       # #5: map pin latitude
    longitude: float | None = None      # #5: map pin longitude
    location_text: str | None = None    # #5: custom typed location text (district/area/landmark)
    location_skipped: bool = False      # #5: whether user skipped map pin
    confirmed_once: bool = False        # whether user has completed all questions and reached confirmation review

    # Metadata & Results
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    prompt_message_id: int | None = None
    llm_result: dict[str, Any] | None = None

    def touch(self) -> None:
        """Update last active timestamp."""
        self.updated_at = time.time()

    def is_expired(self, ttl: float = 900.0) -> bool:
        """Check if session has been inactive past TTL seconds (default 15 minutes)."""
        return (time.time() - self.updated_at) > ttl


class InquiryStateManager:
    """Thread-safe in-memory session manager with automatic TTL eviction."""

    def __init__(self, ttl: float = 900.0) -> None:
        self.ttl = ttl
        self._sessions: dict[int, InquirySession] = {}

    def get_session(self, user_id: int) -> InquirySession | None:
        """Retrieve active session if not expired."""
        self.cleanup_expired()
        session = self._sessions.get(user_id)
        if session:
            if session.is_expired(self.ttl):
                self.clear_session(user_id)
                return None
            session.touch()
        return session

    def create_session(
        self,
        user_id: int,
        chat_id: int,
        teacher_id: int = 0,
        from_index: int = 0,
        teacher: dict[str, Any] | None = None,
        bot_username: str = "",
    ) -> InquirySession:
        """Initialize or reset an inquiry session for a user."""
        self.cleanup_expired()
        t = teacher or {}
        session = InquirySession(
            user_id=user_id,
            chat_id=chat_id,
            teacher_id=teacher_id,
            from_index=from_index,
            teacher_name=t.get("name") or t.get("canonical_name") or "",
            teacher_account=t.get("teacher_account"),
            teacher_city=t.get("city") or t.get("canonical_city"),
            teacher_district=t.get("district"),
            teacher_price=str(t.get("price") or ""),
            teacher_post_link=t.get("teacher_post_link"),
            bot_username=bot_username,
            step=InquiryStep.LOOK,
        )
        self._sessions[user_id] = session
        return session

    def update_step(self, user_id: int, step: InquiryStep) -> InquirySession | None:
        """Advance session to next step."""
        session = self.get_session(user_id)
        if session:
            session.step = step
            session.touch()
        return session

    def clear_session(self, user_id: int) -> None:
        """Purge user session from memory."""
        self._sessions.pop(user_id, None)

    def cleanup_expired(self) -> int:
        """Evict stale sessions past TTL."""
        now = time.time()
        expired_keys = [
            uid for uid, sess in self._sessions.items()
            if (now - sess.updated_at) > self.ttl
        ]
        for uid in expired_keys:
            self._sessions.pop(uid, None)
        return len(expired_keys)


inquiry_state_manager = InquiryStateManager(ttl=900.0)
