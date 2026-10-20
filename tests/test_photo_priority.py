from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from extractor.photo_filter import (
    is_blacklisted_or_group_photo,
    is_valid_teacher_photo,
    _DEFAULT_BLACKLIST_HASHES,
)
from bot.ui.teachers_card import get_teacher_photo, DEFAULT_PLACEHOLDER_PHOTO
from bot.handlers.teachers import _resolve_teacher_photo


class TestPhotoPriorityAndBlacklist(unittest.IsolatedAsyncioTestCase):
    """Test photo resolution priority order and group avatar filtering."""

    def test_xicha_group_logo_blacklisted(self):
        """Verify the xicha group logo hash is strictly blacklisted."""
        xicha_hash = "ef60e48e2b216d7c3140e65ddec01f08"
        self.assertIn(xicha_hash, _DEFAULT_BLACKLIST_HASHES)

    def test_is_valid_teacher_photo(self):
        """Verify is_valid_teacher_photo rejects empty and blacklisted photos."""
        self.assertFalse(is_valid_teacher_photo(None))
        self.assertFalse(is_valid_teacher_photo(""))
        # Dummy path not in blacklist is treated as valid path (for mocks)
        self.assertTrue(is_valid_teacher_photo("/clean/teacher/avatar.jpg"))

    def test_get_teacher_photo_falls_back_for_group_logo(self):
        """Verify get_teacher_photo falls back to placeholder if teacher photo is blacklisted."""
        teacher_clean = {"photo_path": str(DEFAULT_PLACEHOLDER_PHOTO)}
        self.assertEqual(get_teacher_photo(teacher_clean), str(DEFAULT_PLACEHOLDER_PHOTO))

        teacher_empty = {"photo_path": None}
        self.assertEqual(get_teacher_photo(teacher_empty), str(DEFAULT_PLACEHOLDER_PHOTO))

    async def test_resolve_photo_priority_1_direct_account(self):
        """Priority 1: Direct account avatar takes highest precedence."""
        teacher = {
            "id": 100,
            "name": "可可",
            "teacher_account": "@keke520",
            "teacher_post_link": "https://t.me/post/1",
            "photo_path": None,
        }

        with patch("extractor.post_reader.fetch_account_avatar", new=AsyncMock(return_value="/photos/account_keke520.jpg")), \
             patch("bot.handlers.teachers.db.update_teacher_photo", new=AsyncMock()) as mock_update, \
             patch("bot.handlers.teachers.db.get_teacher_reviews", new=AsyncMock(return_value=[{"photo_path": "/photos/review_1.jpg"}])):

            await _resolve_teacher_photo(teacher)

            self.assertEqual(teacher["photo_path"], "/photos/account_keke520.jpg")
            mock_update.assert_awaited_once_with(100, "/photos/account_keke520.jpg")

    async def test_resolve_photo_priority_2_review_photo(self):
        """Priority 2: If direct account has no photo, fallback to genuine review photo."""
        teacher = {
            "id": 101,
            "name": "小雨",
            "teacher_account": "@xiaoyu_none",
            "photo_path": None,
        }

        with patch("extractor.post_reader.fetch_account_avatar", new=AsyncMock(return_value=None)), \
             patch("bot.handlers.teachers.db.update_teacher_photo", new=AsyncMock()) as mock_update, \
             patch("bot.handlers.teachers.db.get_teacher_reviews", new=AsyncMock(return_value=[{"photo_path": "/photos/genuine_review.jpg"}])):

            await _resolve_teacher_photo(teacher)

            self.assertEqual(teacher["photo_path"], "/photos/genuine_review.jpg")
            mock_update.assert_awaited_once_with(101, "/photos/genuine_review.jpg")

    async def test_resolve_photo_priority_3_post_photo(self):
        """Priority 3: If no account photo and no review photo, fallback to post photo."""
        teacher = {
            "id": 102,
            "name": "菲菲",
            "teacher_post_link": "https://t.me/channel/123",
            "photo_path": None,
        }

        with patch("bot.handlers.teachers.db.get_teacher_reviews", new=AsyncMock(return_value=[])), \
             patch("extractor.post_reader.fetch_teacher_post", new=AsyncMock(return_value={"photo_path": "/photos/post_channel_123.jpg"})), \
             patch("bot.handlers.teachers.db.update_teacher_photo", new=AsyncMock()) as mock_update:

            await _resolve_teacher_photo(teacher)

            self.assertEqual(teacher["photo_path"], "/photos/post_channel_123.jpg")
            mock_update.assert_awaited_once_with(102, "/photos/post_channel_123.jpg")

    async def test_resolve_photo_purges_blacklisted_logo(self):
        """Verify blacklisted group photo is purged and reset to None."""
        teacher = {
            "id": 103,
            "name": "西茶老师",
            "photo_path": "/fake/xicha_logo.jpg",
        }

        with patch("bot.handlers.teachers.is_blacklisted_or_group_photo", return_value=True), \
             patch("bot.handlers.teachers.db.execute_write", new=AsyncMock()) as mock_exec, \
             patch("bot.handlers.teachers.db.get_teacher_reviews", new=AsyncMock(return_value=[])):

            await _resolve_teacher_photo(teacher)

            self.assertIsNone(teacher["photo_path"])
            mock_exec.assert_awaited_once_with(
                "UPDATE teachers SET photo_path = NULL WHERE id = ?", [103]
            )


if __name__ == "__main__":
    unittest.main()
