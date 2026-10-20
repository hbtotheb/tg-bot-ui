import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import InlineKeyboardMarkup, Update

from bot.handlers.features import (
    get_homepage_markup,
    on_feature_callback,
    send_homepage,
)


class TestHomepageFeatures(unittest.IsolatedAsyncioTestCase):
    def test_homepage_markup_shows_teachers_and_ads_buttons(self):
        """Verify teacher card, matching inquiry, and ads buttons are shown while others are hidden."""
        for is_admin_val in (False, True):
            markup = get_homepage_markup(lang="zh", user_is_admin=is_admin_val)
            self.assertIsInstance(markup, InlineKeyboardMarkup)

            all_callbacks = [
                btn.callback_data
                for row in markup.inline_keyboard
                for btn in row
            ]

            # Teacher features and ads should be present
            self.assertEqual(all_callbacks, ["tc:swipe:0", "tl:page:0", "inq:start", "feat:ads"])

            # Hidden placeholder buttons must NOT be present
            self.assertNotIn("feat:cities", all_callbacks)
            self.assertNotIn("feat:sub", all_callbacks)
            self.assertNotIn("feat:mode", all_callbacks)
            self.assertNotIn("feat:analytics_today", all_callbacks)

    async def test_on_feature_callback_start_renders_homepage(self):
        """Test feat:start callback edits message with homepage guide and expected buttons."""
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "normal_user"
        update.callback_query.data = "feat:start"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message.photo = None

        context = MagicMock()

        with patch("bot.handlers.features.is_admin", return_value=False), \
             patch("bot.handlers.features.rate_limiter.is_callback_rate_limited", return_value=False):
            await on_feature_callback(update, context)

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_awaited_once()

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text")
        markup = call_args[1].get("reply_markup")

        self.assertIn("全国修车小龙虾", text)
        self.assertIn("最受喜爱老师 (Top 5)", text)
        self.assertIn("最新收录老师 (Top 5)", text)
        self.assertIn("推荐搜索", text)
        self.assertNotIn("Telegram Search Bot", text)
        self.assertNotIn("点击下方 <b>【💃 推荐老师】</b>", text)
        all_callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertEqual(all_callbacks, ["tc:swipe:0", "tl:page:0", "inq:start", "feat:ads"])

    async def test_render_homepage_text_with_popular_and_newest_teachers(self):
        """Verify render_homepage_text outputs concise 1-line cards and clickable search redirect links."""
        from bot.handlers.features import render_homepage_text

        sample_popular = [
            {
                "id": 101,
                "name": "可可",
                "city": "上海",
                "district": "静安",
                "rating": 4.8,
                "review_count": 15,
                "price": 1200,
                "price_p": 1200,
                "teacher_post_link": "https://t.me/test_ch/100",
                "summary": "人照一致甜妹，服务细致配合度高",
            },
        ]
        sample_newest = [
            {
                "id": 102,
                "name": "米娜",
                "city": "上海",
                "district": "徐汇",
                "rating": 4.6,
                "review_count": 8,
                "price": 800,
                "summary": "新入驻隐藏摘要不应显示",
            },
        ]

        text = await render_homepage_text(
            lang="zh",
            bot_username="quanguo_xiuche_bot",
            popular_teachers=sample_popular,
            newest_teachers=sample_newest,
            suggested_districts=["静安", "徐汇", "浦东"],
            suggested_tags=["御姐", "甜妹", "服务好"],
        )
        self.assertIn("全国修车小龙虾", text)
        self.assertIn("AI 智能整理真实报告", text)
        self.assertNotIn("贝叶斯时间衰减", text)
        self.assertIn("最受喜爱老师 (Top 5)", text)
        self.assertIn("🥇", text)
        self.assertIn("可可", text)
        self.assertIn("⭐ 4.8", text)
        self.assertIn("https://t.me/quanguo_xiuche_bot?start=tc_101_0", text)
        self.assertIn("静安", text)
        self.assertIn("¥1200", text)
        self.assertIn("https://t.me/test_ch/100", text)
        self.assertIn("[介绍 ↗]", text)
        self.assertNotIn("[查看 ➔]", text)
        self.assertNotIn("人照一致甜妹，服务细致配合度高", text)

        self.assertIn("最新收录老师 (Top 5)", text)
        self.assertIn("米娜", text)
        self.assertIn("⭐ 4.6", text)
        self.assertIn("徐汇", text)
        self.assertIn("¥800", text)
        self.assertNotIn("新入驻隐藏摘要不应显示", text)

        self.assertIn("推荐搜索（点击直接跳转搜索结果）", text)
        self.assertIn("https://t.me/quanguo_xiuche_bot?start=kw_b64_", text)
        self.assertIn("#静安", text)
        self.assertIn("#御姐", text)
        # Ensure keywords are not raw code blocks that copy to clipboard
        self.assertNotIn("<code>静安</code>", text)
        self.assertNotIn("点击下方 <b>【💃 推荐老师】</b>", text)

    async def test_cmd_start_with_keyword_deeplink_redirects_to_search(self):
        """Verify that /start kw_b64_... deep link decodes keyword and opens teachers list with search query."""
        import base64
        from bot.handlers.search import cmd_start

        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "search_user"
        update.effective_chat.id = 99999
        update.callback_query = None

        b64_kw = base64.urlsafe_b64encode("静安".encode("utf-8")).decode("ascii").rstrip("=")
        context = MagicMock()
        context.args = [f"kw_b64_{b64_kw}"]
        context.user_data = {}

        with patch("bot.handlers.search.db") as mock_db, \
             patch("bot.handlers.teachers.show_teachers_list", new_callable=AsyncMock) as mock_show_list:
            mock_db.register_user = AsyncMock()
            await cmd_start(update, context)

            mock_show_list.assert_awaited_once_with(update, context, page=0, query="静安")
            self.assertEqual(context.user_data.get("teacher_search_query"), "静安")

    async def test_on_feature_callback_start_with_photo_replaces_message(self):
        """When returning from a photo view, the photo message is deleted and text message sent."""
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "normal_user"
        update.effective_chat.id = 99999
        update.callback_query.data = "feat:start"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.message.delete = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("bot.handlers.features.is_admin", return_value=False), \
             patch("bot.handlers.features.rate_limiter.is_callback_rate_limited", return_value=False):
            await on_feature_callback(update, context)

        update.callback_query.message.delete.assert_awaited_once()
        context.bot.send_message.assert_awaited_once()
        sent_markup = context.bot.send_message.call_args[1]["reply_markup"]
        all_callbacks = [btn.callback_data for row in sent_markup.inline_keyboard for btn in row]
        self.assertEqual(all_callbacks, ["tc:swipe:0", "tl:page:0", "inq:start", "feat:ads"])

    async def test_legacy_placeholder_callbacks_still_work_gracefully(self):
        """Ensure historical buttons for ads, cities, sub, mode still show placeholder with back button."""
        for feat_name in ["ads", "cities", "sub", "mode"]:
            update = MagicMock(spec=Update)
            update.effective_user.id = 12345
            update.effective_user.username = "normal_user"
            update.callback_query.data = f"feat:{feat_name}"
            update.callback_query.answer = AsyncMock()
            update.callback_query.edit_message_text = AsyncMock()

            context = MagicMock()

            with patch("bot.handlers.features.rate_limiter.is_callback_rate_limited", return_value=False):
                await on_feature_callback(update, context)

            update.callback_query.edit_message_text.assert_awaited_once()
            markup = update.callback_query.edit_message_text.call_args[1]["reply_markup"]
            self.assertEqual(markup.inline_keyboard[0][0].callback_data, "feat:start")

    async def test_cmd_start_sends_homepage(self):
        """Verify that sending /start directly responds with the bot homepage."""
        from bot.handlers.search import cmd_start
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "normal_user"
        update.effective_chat.id = 99999
        update.callback_query = None
        update.effective_message.reply_text = AsyncMock()

        context = MagicMock()
        context.args = []

        with patch("bot.handlers.search.db") as mock_db, \
             patch("bot.handlers.features.is_admin", return_value=False):
            mock_db.register_user = AsyncMock()
            await cmd_start(update, context)

        update.effective_message.reply_text.assert_awaited_once()
        sent_markup = update.effective_message.reply_text.call_args[1]["reply_markup"]
        all_callbacks = [btn.callback_data for row in sent_markup.inline_keyboard for btn in row]
        self.assertEqual(all_callbacks, ["tc:swipe:0", "tl:page:0", "inq:start", "feat:ads"])

    async def test_on_text_sends_homepage(self):
        """Verify that sending a text message directly responds with the bot homepage."""
        from bot.handlers.search import on_text
        update = MagicMock(spec=Update)
        update.effective_user.id = 12345
        update.effective_user.username = "normal_user"
        update.effective_chat.id = 99999
        update.callback_query = None
        update.message.text = "hello"
        update.effective_message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.search.db") as mock_db, \
             patch("bot.handlers.search.rate_limiter.is_message_rate_limited", return_value=False), \
             patch("bot.inquiry.handlers.on_inquiry_text", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.features.is_admin", return_value=False):
            mock_db.register_user = AsyncMock()
            await on_text(update, context)

        update.effective_message.reply_text.assert_awaited_once()
        sent_markup = update.effective_message.reply_text.call_args[1]["reply_markup"]
        all_callbacks = [btn.callback_data for row in sent_markup.inline_keyboard for btn in row]
        self.assertEqual(all_callbacks, ["tc:swipe:0", "tl:page:0", "inq:start", "feat:ads"])


if __name__ == "__main__":
    unittest.main()

