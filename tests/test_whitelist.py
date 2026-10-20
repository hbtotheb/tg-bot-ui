from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "bot") not in sys.path:
    sys.path.insert(0, str(ROOT / "bot"))

from bot.core.whitelist import (
    get_whitelisted_user_ids,
    get_whitelisted_usernames,
    is_whitelisted,
    record_user_identity,
)
from bot.core.rate_limiter import UserRateLimiter
from bot.inquiry.rate_limiter import InquiryRateLimiter


class TestWhitelist(unittest.TestCase):
    """Test account whitelist parsing, username resolution, and rate limiter bypass."""

    def setUp(self):
        # Clear cached identities
        from bot.core.whitelist import _user_id_to_username
        _user_id_to_username.clear()

    @patch.dict(os.environ, {"ADMIN_USER_IDS": "111,222", "RATE_LIMIT_WHITELIST": "333, @product_guy, huaibo"})
    def test_env_whitelist_parsing(self):
        ids = get_whitelisted_user_ids()
        self.assertIn(111, ids)
        self.assertIn(222, ids)
        self.assertIn(333, ids)

        names = get_whitelisted_usernames()
        self.assertIn("product_guy", names)
        self.assertIn("huaibo", names)

        # Test is_whitelisted by ID
        self.assertTrue(is_whitelisted(user_id=111))
        self.assertTrue(is_whitelisted(user_id=333))
        self.assertFalse(is_whitelisted(user_id=999))

        # Test is_whitelisted by username
        self.assertTrue(is_whitelisted(username="@Product_Guy"))
        self.assertTrue(is_whitelisted(username="huaibo"))
        self.assertFalse(is_whitelisted(username="stranger"))

    @patch.dict(os.environ, {"INTERNAL_USERS": "444, @internal_dev"})
    def test_internal_users_env_format(self):
        self.assertTrue(is_whitelisted(user_id=444))
        self.assertTrue(is_whitelisted(username="@INTERNAL_DEV"))
        self.assertFalse(is_whitelisted(user_id=555))

    def test_whitelist_file_support(self,):
        whitelist_data = {
            "user_ids": [77777],
            "usernames": ["lead_designer"]
        }
        with patch("bot.core.whitelist.WHITELIST_FILE", Path("temp_whitelist_test.json")), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(whitelist_data))):
            self.assertTrue(is_whitelisted(user_id=77777))
            self.assertTrue(is_whitelisted(username="@lead_designer"))
            self.assertFalse(is_whitelisted(user_id=88888))

    @patch.dict(os.environ, {"RATE_LIMIT_WHITELIST": "@product_lead"})
    def test_dynamic_username_identity_binding(self):
        # User 123456 interacts with username @product_lead
        self.assertTrue(is_whitelisted(user_id=123456, username="@product_lead"))

        # Subsequent check with only user_id=123456 (no username passed)
        self.assertTrue(is_whitelisted(user_id=123456))

    @patch.dict(os.environ, {"RATE_LIMIT_WHITELIST": "999, @product_guy"})
    def test_user_rate_limiter_bypass(self):
        limiter = UserRateLimiter(callback_cooldown=0.5, message_cooldown=0.5)

        # Normal user gets rate limited on rapid clicks
        self.assertFalse(limiter.is_callback_rate_limited(user_id=100))
        self.assertTrue(limiter.is_callback_rate_limited(user_id=100))

        # Whitelisted by ID: never limited
        self.assertFalse(limiter.is_callback_rate_limited(user_id=999))
        self.assertFalse(limiter.is_callback_rate_limited(user_id=999))
        self.assertFalse(limiter.is_callback_rate_limited(user_id=999))

        # Whitelisted by Username: never limited
        self.assertFalse(limiter.is_callback_rate_limited(user_id=888, username="@product_guy"))
        self.assertFalse(limiter.is_callback_rate_limited(user_id=888, username="@product_guy"))
        self.assertFalse(limiter.is_message_rate_limited(user_id=888, username="@product_guy"))

    @patch.dict(os.environ, {"RATE_LIMIT_WHITELIST": "999, @product_guy"})
    def test_inquiry_rate_limiter_bypass(self):
        limiter = InquiryRateLimiter(action_cooldown=0.5, submission_cooldown=15.0, max_daily_submissions=1)

        # Normal user hits action cooldown
        self.assertFalse(limiter.is_action_limited(user_id=100))
        self.assertTrue(limiter.is_action_limited(user_id=100))

        # Whitelisted user bypasses action cooldown
        self.assertFalse(limiter.is_action_limited(user_id=999))
        self.assertFalse(limiter.is_action_limited(user_id=999))
        self.assertFalse(limiter.is_action_limited(user_id=888, username="@product_guy"))

        # Whitelisted user bypasses submission cooldown and daily limit
        limiter.record_submission(user_id=999)
        limited, reason = limiter.is_submission_limited(user_id=999)
        self.assertFalse(limited)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
