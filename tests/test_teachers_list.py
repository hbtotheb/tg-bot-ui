import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import InlineKeyboardMarkup, Update

from bot.ui.teachers_list import (
    format_teachers_list,
    format_teacher_search_prompt,
    PAGE_SIZE,
)
from bot.handlers.teachers import (
    cmd_teachers_list,
    on_teacher_list_callback,
    show_teachers_list,
    show_teacher_card_by_id,
)
from bot.handlers.search import cmd_start


class TestTeachersListUI(unittest.TestCase):
    def setUp(self):
        self.mock_teachers = [
            {
                "id": i + 1,
                "name": f"老师{i + 1}",
                "city": "上海",
                "district": "普陀" if i % 2 == 0 else "静安",
                "price_p": 1000 + i * 100,
                "price_pp": 1800 + i * 100,
                "rating": 4.5 + (i * 0.05),
                "review_count": 5 + i,
                "tags": "成熟御姐, 高挑长腿",
                "teacher_post_link": "https://t.me/channel/100" if i == 0 else None,
            }
            for i in range(8)
        ]

    def test_format_teachers_list_full_page_with_clickable_links(self):
        """Test formatting a page of 8 teachers with clickable in-text links and clean keyboard."""
        text, markup = format_teachers_list(
            teachers=self.mock_teachers,
            page=0,
            total=20,
            page_size=8,
            bot_username="test_bot",
        )

        self.assertIn("精选老师名录 (共 20 位)", text)
        self.assertIn("第 1/3 页", text)
        # Verify in-chat clickable links on teacher name and [查看 ➔]
        self.assertIn('<a href="https://t.me/test_bot?start=tc_1_0"><b>老师1</b></a>', text)
        self.assertIn('<a href="https://t.me/test_bot?start=tc_1_0">[查看 ➔]</a>', text)
        self.assertIn('<a href="https://t.me/channel/100">[介绍帖 ↗]</a>', text)
        self.assertIn("📍 上海 · 普陀", text)
        self.assertIn("¥1000/1P · ¥1800/2P", text)
        self.assertIn("#成熟御姐", text)

        kb = markup.inline_keyboard
        all_callbacks = [b.callback_data for row in kb for b in row]

        # Individual jump buttons must NOT be present in keyboard
        self.assertNotIn("tl:view:1:0", all_callbacks)
        self.assertNotIn("tl:view:8:0", all_callbacks)

        # Row 0: Pagination
        page_callbacks = [b.callback_data for b in kb[0]]
        self.assertIn("tl:page:1", page_callbacks)

        # Row 1: Search button
        self.assertEqual(kb[1][0].callback_data, "tl:search")

        # Row 2: Home button (swipe card button removed)
        self.assertEqual(kb[2][0].callback_data, "feat:start")
        self.assertNotIn("tc:swipe:0", all_callbacks)

    def test_format_teachers_list_with_search_query(self):
        """Test formatting search results with active query and clear search button."""
        text, markup = format_teachers_list(
            teachers=self.mock_teachers[:3],
            page=0,
            total=3,
            page_size=8,
            query="普陀",
            bot_username="test_bot",
        )

        self.assertIn("搜索结果 (共 3 位)", text)
        self.assertIn("当前检索：</b> <code>普陀</code>", text)

        all_callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("tl:search", all_callbacks)
        self.assertIn("tl:clearsearch", all_callbacks)
        # Still no top jump buttons
        self.assertNotIn("tl:view:1:0", all_callbacks)

    def test_format_teachers_list_empty(self):
        """Test empty list view when no teachers match query."""
        text, markup = format_teachers_list(
            teachers=[],
            page=0,
            total=0,
            page_size=8,
            query="不存在的老师",
            bot_username="test_bot",
        )

        self.assertIn("未找到与", text)
        self.assertIn("不存在的老师", text)

    def test_format_teacher_search_prompt(self):
        """Test teacher search prompt rendering with return button."""
        text, markup = format_teacher_search_prompt()
        self.assertIn("搜索老师名录", text)
        all_callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("tl:page:0", all_callbacks)
        self.assertIn("feat:start", all_callbacks)


class TestTeachersListHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_show_teachers_list_fetches_from_db(self):
        """Verify show_teachers_list queries database with page size 8 and sends message."""
        update = MagicMock(spec=Update)
        update.callback_query = None
        update.effective_message.reply_text = AsyncMock()

        context = MagicMock()
        context.bot.username = "test_bot"
        mock_teachers = [{"id": 1, "name": "测试老师", "city": "上海", "rating": 5.0, "review_count": 2}]

        with patch("bot.handlers.teachers.db.count_teachers", new_callable=AsyncMock) as mock_count, \
             patch("bot.handlers.teachers.db.search_teachers", new_callable=AsyncMock) as mock_search:
            mock_count.return_value = 1
            mock_search.return_value = mock_teachers

            await show_teachers_list(update, context, page=0, query="上海")

            mock_count.assert_awaited_once_with(query="上海", status="active")
            mock_search.assert_awaited_once_with(
                query="上海", status="active", sort_by="rank", limit=8, offset=0
            )
            update.effective_message.reply_text.assert_awaited_once()

    async def test_on_teacher_list_callback_page_navigation(self):
        """Test tl:page:<page> callback renders target page."""
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "test_user"
        update.callback_query.data = "tl:page:2"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message.photo = None

        context = MagicMock()
        context.user_data = {"teacher_search_query": "静安"}

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db.count_teachers", new_callable=AsyncMock, return_value=24), \
             patch("bot.handlers.teachers.db.search_teachers", new_callable=AsyncMock, return_value=[]):
            await on_teacher_list_callback(update, context)

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_awaited_once()

    async def test_on_teacher_list_callback_search_prompt(self):
        """Test tl:search sets awaiting_teacher_search and renders search prompt."""
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "test_user"
        update.callback_query.data = "tl:search"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message.photo = None

        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False):
            await on_teacher_list_callback(update, context)

        self.assertTrue(context.user_data.get("awaiting_teacher_search"))
        update.callback_query.edit_message_text.assert_awaited_once()

    async def test_on_teacher_list_callback_clearsearch(self):
        """Test tl:clearsearch clears stored query and resets to page 0."""
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "test_user"
        update.callback_query.data = "tl:clearsearch"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message.photo = None

        context = MagicMock()
        context.user_data = {"teacher_search_query": "普陀", "awaiting_teacher_search": True}

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db.count_teachers", new_callable=AsyncMock, return_value=10), \
             patch("bot.handlers.teachers.db.search_teachers", new_callable=AsyncMock, return_value=[]):
            await on_teacher_list_callback(update, context)

        self.assertNotIn("teacher_search_query", context.user_data)
        self.assertNotIn("awaiting_teacher_search", context.user_data)

    async def test_cmd_start_tc_deep_link_opens_teacher_card(self):
        """Test /start tc_42_1 deep link command opens single teacher card with back to list button."""
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "test_user"
        update.effective_message.reply_photo = AsyncMock()
        update.effective_message.reply_text = AsyncMock()

        context = MagicMock()
        context.args = ["tc_42_1"]

        mock_teacher = {
            "id": 42,
            "name": "小樱",
            "city": "上海",
            "district": "静安",
            "price": 1000,
            "rating": 4.9,
            "review_count": 8,
            "photo_path": None,
        }

        with patch("bot.handlers.search.db.register_user", new_callable=AsyncMock), \
             patch("bot.handlers.teachers.db.get_teacher", new_callable=AsyncMock, return_value=mock_teacher), \
             patch("bot.handlers.teachers._resolve_teacher_link", new_callable=AsyncMock), \
             patch("bot.handlers.teachers._resolve_teacher_photo", new_callable=AsyncMock):
            await cmd_start(update, context)

        # Either photo or text was sent
        self.assertTrue(
            update.effective_message.reply_photo.called or update.effective_message.reply_text.called
        )
        call_args = (
            update.effective_message.reply_photo.call_args
            if update.effective_message.reply_photo.called
            else update.effective_message.reply_text.call_args
        )
        sent_markup = call_args[1]["reply_markup"]
        all_callbacks = [b.callback_data for row in sent_markup.inline_keyboard for b in row]
        # Should have back button pointing to tl:page:1
        self.assertIn("tl:page:1", all_callbacks)


if __name__ == "__main__":
    unittest.main()
