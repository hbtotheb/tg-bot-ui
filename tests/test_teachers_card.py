from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.ui.teachers_card import (
    format_empty_card,
    format_review_detail,
    format_teacher_card,
    format_teacher_reviews,
    safe_truncate_html,
)
from bot.handlers.teachers import cmd_teachers, on_teacher_card_callback


class TestTeachersCardUI(unittest.TestCase):
    """Test unit formatting and interaction controls for Tinder-like teacher cards."""

    def setUp(self):
        self.sample_teacher = {
            "id": 88,
            "name": "小樱",
            "canonical_name": "小樱",
            "message_link": "https://t.me/c/1622463102/7091",
            "rating": 4.88,
            "city": "上海",
            "district": "静安",
            "landmark": "静安寺",
            "price": 800.0,
            "tags": "颜值高, 配合好, 大长腿, 真胸C杯",
            "review_count": 5,
            "rank_score": 4.25,
            "score_visual": 4.9,
            "score_body": 4.8,
            "score_service": 4.9,
            "score_env": 4.5,
            "rating_look": 5.0,
            "rating_leg": 5.0,
            "rating_breast": 4.8,
            "teacher_account": "@xiaoying520",
            "teacher_post_link": "https://t.me/shjiaodian/24542",
        }

    def test_format_teacher_card_first(self):
        """Test formatting the first teacher card (index 0) with teacher post link and reviews button."""
        text, markup = format_teacher_card(self.sample_teacher, index=0, total=10)

        # Content checks
        self.assertNotIn("精选老师", text)
        self.assertNotIn("探探卡片", text)
        self.assertNotIn("(1 / 10)", text)
        self.assertIn("小樱", text)
        self.assertIn('href="https://t.me/shjiaodian/24542"', text)
        self.assertNotIn("https://t.me/c/1622463102/7091", text)
        self.assertNotIn("点击跳转原帖 ↗", text)
        self.assertNotIn("4.88", text)
        self.assertNotIn("综合评分", text)
        self.assertNotIn("⭐⭐⭐⭐⭐", text)
        self.assertNotIn("颜值外貌", text)
        self.assertNotIn("高分亮点", text)
        self.assertIn("上海 · 静安 · 静安寺", text)
        self.assertIn("800 / 1P", text)
        self.assertIn("#颜值高", text)
        self.assertIn("#大长腿", text)

        # Button checks
        kb = markup.inline_keyboard
        # Row 1: Only Next button (since index=0)
        self.assertEqual(len(kb[0]), 1)
        self.assertEqual(kb[0][0].callback_data, "tc:swipe:1")
        self.assertIn("下一位", kb[0][0].text)

        # Row 2: Teacher Account contact URL button and Teacher Post Link button
        self.assertEqual(len(kb[1]), 2)
        self.assertEqual(kb[1][0].url, "https://t.me/xiaoying520")
        self.assertIn("老师直联 ↗", kb[1][0].text)
        self.assertEqual(kb[1][1].url, "https://t.me/shjiaodian/24542")
        self.assertIn("老师介绍帖 ↗", kb[1][1].text)

        # Row 3: Reviews button
        self.assertEqual(kb[2][0].callback_data, "tc:rev:88:0")
        self.assertIn("查看所有评测", kb[2][0].text)
        self.assertIn("(5 篇)", kb[2][0].text)

        # Row 4: Main menu button
        self.assertEqual(kb[3][0].callback_data, "feat:start")

    def test_format_teacher_card_no_link(self):
        """Test card without teacher_post_link and teacher_account gracefully omits URL button."""
        teacher_no_link = dict(self.sample_teacher)
        teacher_no_link["teacher_post_link"] = None
        teacher_no_link["teacher_account"] = None
        text, markup = format_teacher_card(teacher_no_link, index=0, total=5)
        self.assertNotIn("点击跳转介绍帖 ↗", text)
        self.assertNotIn("老师账号", text)
        kb = markup.inline_keyboard
        # Row 1: Swipe button
        self.assertEqual(len(kb[0]), 1)
        # Row 2: Reviews button
        self.assertEqual(kb[1][0].callback_data, "tc:rev:88:0")
        self.assertIn("查看所有评测 (5 篇)", kb[1][0].text)
        # Row 3: Main menu button
        self.assertEqual(len(kb), 3)
        self.assertEqual(kb[2][0].callback_data, "feat:start")

    def test_format_teacher_card_with_booking_url(self):
        """Test card uses booking/redirect URL as standard teacher account link without extra redirect button."""
        teacher_bot = dict(self.sample_teacher)
        teacher_bot["teacher_account"] = None
        teacher_bot["booking_url"] = "https://t.me/zhaocha_bot?start=yueKe_123"
        text, markup = format_teacher_card(teacher_bot, index=0, total=5)
        kb = markup.inline_keyboard
        btn_texts = [b.text for b in kb[1]]
        self.assertTrue(any("老师直联" in t for t in btn_texts))
        self.assertFalse(any("快捷预约" in t for t in btn_texts))
        self.assertTrue(any(b.url == "https://t.me/zhaocha_bot?start=yueKe_123" for b in kb[1]))

    def test_format_teacher_card_with_summary(self):
        """Test that card formats summary prominently and does not display tags when summary is present."""
        teacher_with_summary = dict(self.sample_teacher)
        teacher_with_summary["summary"] = "长相清秀性格温柔，服务细节周到不催钟，手法专业体验极佳"
        text, _ = format_teacher_card(teacher_with_summary, index=0, total=5)
        self.assertIn("💡 <b>评测总结：</b>", text)
        self.assertIn("长相清秀性格温柔，服务细节周到不催钟，手法专业体验极佳", text)
        self.assertNotIn("🏷️ <b>特色印象：</b>", text)

    def test_format_teacher_card_with_inactive_status(self):
        """Test that inactive teachers display appropriate status hint notices."""
        teacher_inactive = dict(self.sample_teacher)
        teacher_inactive["status"] = "inactive"
        teacher_inactive["status_reason"] = "post_resting"
        text, _ = format_teacher_card(teacher_inactive, index=0, total=5)
        self.assertIn("状态提示：", text)
        self.assertIn("休假/暂停开课", text)

        teacher_deleted = dict(self.sample_teacher)
        teacher_deleted["status"] = "inactive"
        teacher_deleted["status_reason"] = "account_deleted"
        text2, _ = format_teacher_card(teacher_deleted, index=0, total=5)
        self.assertIn("状态提示：", text2)
        self.assertIn("账号疑似已注销或已改名", text2)

    def test_format_teacher_card_middle(self):
        """Test formatting a middle teacher card (both Prev and Next buttons)."""
        text, markup = format_teacher_card(self.sample_teacher, index=3, total=10)
        self.assertNotIn("(4 / 10)", text)

        kb = markup.inline_keyboard
        # Row 1: Prev and Next
        self.assertEqual(len(kb[0]), 2)
        self.assertEqual(kb[0][0].callback_data, "tc:swipe:2")
        self.assertIn("上一位", kb[0][0].text)
        self.assertEqual(kb[0][1].callback_data, "tc:swipe:4")
        self.assertIn("下一位", kb[0][1].text)

    def test_format_teacher_card_last(self):
        """Test formatting the last teacher card (shows restart button)."""
        text, markup = format_teacher_card(self.sample_teacher, index=9, total=10)
        self.assertNotIn("(10 / 10)", text)

        kb = markup.inline_keyboard
        # Row 1: Prev and Restart
        self.assertEqual(len(kb[0]), 2)
        self.assertEqual(kb[0][0].callback_data, "tc:swipe:8")
        self.assertEqual(kb[0][1].callback_data, "tc:swipe:0")
        self.assertIn("从头重新浏览", kb[0][1].text)

    def test_format_teacher_card_price_variants(self):
        """Test teacher card price display for both P/PP, P only, PP only, and missing price."""
        # 1. Both P and PP
        t_both = dict(self.sample_teacher, price_p=800.0, price_pp=1500.0)
        text, _ = format_teacher_card(t_both, index=0, total=1)
        self.assertIn("800 / 1P · 1500 / 2P", text)

        # 2. Only P
        t_p = dict(self.sample_teacher, price_p=900.0, price_pp=None, price=900.0)
        text, _ = format_teacher_card(t_p, index=0, total=1)
        self.assertIn("900 / 1P", text)
        self.assertNotIn("2P", text)

        # 3. Only PP
        t_pp = dict(self.sample_teacher, price_p=None, price_pp=1600.0, price=None)
        text, _ = format_teacher_card(t_pp, index=0, total=1)
        self.assertIn("1600 / 2P", text)

        # 4. Fallback from price to P
        t_fallback = dict(self.sample_teacher, price_p=None, price_pp=None, price=1000.0)
        text, _ = format_teacher_card(t_fallback, index=0, total=1)
        self.assertIn("1000 / 1P", text)

        # 5. Missing price
        t_empty = dict(self.sample_teacher, price_p=None, price_pp=None, price=None)
        text, _ = format_teacher_card(t_empty, index=0, total=1)
        self.assertIn("暂无标价 / 详询", text)

    def test_format_empty_card(self):
        """Test empty card state when no teachers are present."""
        text, markup = format_empty_card()
        self.assertIn("暂无评测聚合的老师数据", text)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "feat:start")

    def test_format_teacher_reviews(self):
        """Test formatting reviews view with reviewer username, date, KOL badge, and shill badge."""
        sample_reviews = [
            {
                "id": 101,
                "username": "kol_reviewer",
                "first_name": "老司机",
                "date": 1788356740,
                "rating": 4.9,
                "is_pro": 1,
                "authenticity_score": 0.95,
                "tags": "符文, 会夹",
                "content": "真人超级好看，配合度高，非常满意！",
                "message_link": "https://t.me/c/1622463102/7091",
                "chat_title": "精选评测群",
            },
            {
                "id": 102,
                "username": "shill_bot",
                "first_name": None,
                "date": 1788324476,
                "rating": 5.0,
                "is_pro": 0,
                "authenticity_score": 0.35,
                "tags": "大长腿",
                "content": "全网天花板，极品尤物包满意！",
                "message_link": "https://t.me/c/1622463102/7090",
                "chat_title": "精选评测群",
            },
        ]
        # 1. Overview list (both reviews fit on Page 0 with page_size=6)
        text, markup = format_teacher_reviews(
            self.sample_teacher, sample_reviews, from_index=3, page=0, bot_username="test_search_bot"
        )
        self.assertIn("【小樱】的全部评测 (2 篇)", text)
        self.assertNotIn("综合评分", text)
        self.assertNotIn("⭐", text)

        # Reviewer 1 & Reviewer 2 both shown on page 0 with metadata only
        self.assertIn("老司机 (@kol_reviewer)", text)
        self.assertIn("精选评测群", text)
        self.assertIn("2026-", text)
        self.assertIn("@shill_bot", text)

        # NO snippets or review body on list page
        self.assertNotIn("真人超级好看", text)
        self.assertNotIn("全网天花板", text)
        self.assertNotIn("blockquote expandable", text)
        self.assertNotIn("<blockquote>", text)

        # Inline redirect link in text (deep-linked to bot review detail subpage)
        self.assertIn("https://t.me/test_search_bot?start=rdtl_88_101_3_0_1", text)
        self.assertIn("https://t.me/test_search_bot?start=rdtl_88_102_3_0_2", text)
        self.assertIn("[详情 ↗]", text)

        # Clutter / badges removed
        self.assertNotIn("👑", text)
        self.assertNotIn("KOL 达人认证", text)
        self.assertNotIn("⚠️", text)
        self.assertNotIn("疑似托评", text)

        # NO external buttons in keyboard for viewing reviews!
        kb = markup.inline_keyboard
        all_btn_texts = [b.text for row in kb for b in row]
        for t_val in all_btn_texts:
            self.assertNotIn("📖 查看", t_val)

        # Row 0: Action controls (Contact & Post Link)
        self.assertEqual(len(kb[0]), 2)
        self.assertEqual(kb[0][0].url, "https://t.me/xiaoying520")
        self.assertIn("老师直联 ↗", kb[0][0].text)
        self.assertEqual(kb[0][1].url, "https://t.me/shjiaodian/24542")
        self.assertIn("老师介绍帖 ↗", kb[0][1].text)

        # Row 1: Back to teacher card and Home
        self.assertEqual(len(kb[1]), 2)
        self.assertEqual(kb[1][0].callback_data, "tc:swipe:3")
        self.assertIn("返回老师卡片", kb[1][0].text)
        self.assertEqual(kb[1][1].callback_data, "feat:start")
        self.assertIn("返回机器人首页", kb[1][1].text)

        # 2. Test fallback to message_link when bot_username is None
        fb_text, _ = format_teacher_reviews(self.sample_teacher, sample_reviews, from_index=3, page=0)
        self.assertIn('href="https://t.me/c/1622463102/7091"', fb_text)
        self.assertIn("[详情 ↗]", fb_text)

        # 3. Test pagination when total reviews > page_size (e.g. 7 reviews with page_size=6)
        seven_reviews = sample_reviews + [
            {"id": 103, "date": 1788324477},
            {"id": 104, "date": 1788324478},
            {"id": 105, "date": 1788324479},
            {"id": 106, "date": 1788324480},
            {"id": 107, "date": 1788324481},
        ]
        page_text, page_markup = format_teacher_reviews(
            self.sample_teacher, seven_reviews, from_index=3, page=0, page_size=6
        )
        self.assertIn("[1/2页]", page_text)
        page_kb = page_markup.inline_keyboard
        # Row 0: pagination controls
        self.assertEqual(page_kb[0][0].text, "📄 1/2")
        self.assertEqual(page_kb[0][1].callback_data, "tc:rev:88:3:1")
        self.assertIn("下一页", page_kb[0][1].text)

    def test_safe_truncate_html_avoids_broken_tags(self):
        """Test that safe_truncate_html never leaves broken tags like </a or <a without closing tag."""
        html_input = '<b>Title</b> <a href="https://t.me/test_bot?start=rdtl_1_2">[详情 ↗]</a>'
        for length in range(10, len(html_input) + 5):
            truncated = safe_truncate_html(html_input, max_chars=length)
            self.assertNotIn("</a…", truncated)
            self.assertNotIn("<a…", truncated)
            if "<a" in truncated:
                self.assertIn("</a>", truncated)
            if "<b>" in truncated:
                self.assertIn("</b>", truncated)

    def test_format_review_detail(self):
        """Test formatting single review detail subpage with full content and original post link."""
        sample_review = {
            "id": 101,
            "username": "kol_reviewer",
            "first_name": "老司机",
            "date": 1788356740,
            "rating": 4.9,
            "content": "真人超级好看，配合度高，非常满意！全程态度温柔细致，强烈推荐大家去体验！",
            "message_link": "https://t.me/c/1622463102/7091",
            "chat_title": "精选评测群",
        }
        text, markup = format_review_detail(self.sample_teacher, sample_review, review_num=1, from_index=3, page=0)
        self.assertIn("【小樱】· 评测全文 (#1)", text)
        self.assertIn("老司机 (@kol_reviewer)", text)
        self.assertIn("精选评测群", text)
        self.assertIn("4.9", text)
        self.assertIn("真人超级好看，配合度高，非常满意！", text)

        kb = markup.inline_keyboard
        # Row 0: Link to original post
        self.assertEqual(kb[0][0].url, "https://t.me/c/1622463102/7091")
        self.assertIn("查看评测原帖 ↗", kb[0][0].text)

        # Teacher contact and teacher post buttons should NOT be present on the review detail subpage
        all_btn_texts = [btn.text for row in kb for btn in row]
        self.assertFalse(any("老师直联" in t for t in all_btn_texts))
        self.assertFalse(any("老师介绍帖" in t for t in all_btn_texts))

        # Row 1: Back to reviews list
        self.assertEqual(kb[1][0].callback_data, "tc:rev:88:3:0")
        self.assertIn("返回评测列表", kb[1][0].text)

        # Row 2: Back to teacher card & home combined
        self.assertEqual(len(kb[2]), 2)
        self.assertEqual(kb[2][0].callback_data, "tc:swipe:3")
        self.assertIn("返回老师卡片", kb[2][0].text)
        self.assertEqual(kb[2][1].callback_data, "feat:start")
        self.assertIn("返回机器人首页", kb[2][1].text)

    def test_get_teacher_photo_fallback(self):
        """Test get_teacher_photo returns placeholder when photo_path is missing or non-existent."""
        from bot.ui.teachers_card import get_teacher_photo, DEFAULT_PLACEHOLDER_PHOTO
        self.assertEqual(get_teacher_photo({}), str(DEFAULT_PLACEHOLDER_PHOTO))
        self.assertEqual(get_teacher_photo({"photo_path": "non_existent.jpg"}), str(DEFAULT_PLACEHOLDER_PHOTO))

    def test_caption_length_safety(self):
        """Test teacher card and reviews stay within Telegram 1024-character caption limit."""
        long_teacher = dict(self.sample_teacher)
        long_teacher["tags"] = ", ".join(["超长豪华标签体验测试"] * 40)
        caption, _ = format_teacher_card(long_teacher, index=0, total=1)
        self.assertLessEqual(len(caption), 1000)

        long_reviews = [
            {"id": i, "date": 1788356740, "rating": 5.0, "content": "这是一段非常详尽且长篇大论的体验报告评测内容。" * 20}
            for i in range(5)
        ]
        rev_caption, _ = format_teacher_reviews(long_teacher, long_reviews, from_index=0)
        self.assertLessEqual(len(rev_caption), 1000)


class TestTeacherHandlers(unittest.IsolatedAsyncioTestCase):
    """Test Telegram bot command and callback execution for teacher swipe cards."""

    async def test_cmd_teachers_flow(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_user.username = "test_user"
        update.effective_chat.id = 67890
        update.effective_message.reply_photo = AsyncMock()
        update.effective_message.reply_text = AsyncMock()

        context = MagicMock()

        with patch("bot.handlers.teachers.db") as mock_db:
            mock_db.register_user = AsyncMock()
            mock_db.count_teachers = AsyncMock(return_value=5)
            mock_db.search_teachers = AsyncMock(return_value=[{"id": 1, "name": "菲菲", "rating": 4.9}])
            mock_db.get_teacher_reviews = AsyncMock(return_value=[])

            await cmd_teachers(update, context)

            mock_db.register_user.assert_awaited_once()
            mock_db.count_teachers.assert_awaited_once()
            mock_db.search_teachers.assert_awaited_once_with(sort_by="rank", limit=1, offset=0)
            update.effective_message.reply_photo.assert_awaited_once()

    async def test_on_teacher_card_callback_swipe_photo(self):
        """Test in-place media edit when current message is already a photo message."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "tc:swipe:2"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_media = AsyncMock()

        context = MagicMock()

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.count_teachers = AsyncMock(return_value=10)
            mock_db.search_teachers = AsyncMock(return_value=[{"id": 99, "name": "安安", "rating": 4.85}])
            mock_db.get_teacher_reviews = AsyncMock(return_value=[])

            await on_teacher_card_callback(update, context)

            update.callback_query.answer.assert_awaited_once()
            mock_db.search_teachers.assert_awaited_once_with(sort_by="rank", limit=1, offset=2)
            update.callback_query.edit_message_media.assert_awaited_once()

    async def test_on_teacher_card_callback_swipe_from_text(self):
        """Test transition from text menu message to photo message."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_chat.id = 67890
        update.callback_query.data = "tc:swipe:0"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = None
        update.callback_query.message.delete = AsyncMock()
        context = MagicMock()
        context.bot.send_photo = AsyncMock()

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.count_teachers = AsyncMock(return_value=10)
            mock_db.search_teachers = AsyncMock(return_value=[{"id": 99, "name": "安安", "rating": 4.85}])
            mock_db.get_teacher_reviews = AsyncMock(return_value=[])

            await on_teacher_card_callback(update, context)

            update.callback_query.message.delete.assert_awaited_once()
            context.bot.send_photo.assert_awaited_once()

    async def test_on_teacher_card_callback_reviews_photo(self):
        """Test rev callback on photo message fetches teacher reviews and edits message caption."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "tc:rev:99:2"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_caption = AsyncMock()

        context = MagicMock()

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.get_teacher = AsyncMock(return_value={
                "id": 99,
                "name": "安安",
                "rating": 4.85,
                "teacher_account": "@anan520",
                "teacher_post_link": "https://t.me/c/123/456",
                "photo_path": "photo.jpg",
            })
            mock_db.get_teacher_reviews = AsyncMock(return_value=[
                {
                    "id": 1,
                    "username": "kol_tester",
                    "first_name": "老铁",
                    "chat_title": "精选群",
                    "date": 1788356740,
                    "content": "好评评测",
                }
            ])

            await on_teacher_card_callback(update, context)

            update.callback_query.answer.assert_awaited_once()
            mock_db.get_teacher.assert_awaited_once_with(99)
            mock_db.get_teacher_reviews.assert_awaited_once_with(99, limit=50)
            update.callback_query.edit_message_caption.assert_awaited_once()
            call_kwargs = update.callback_query.edit_message_caption.call_args.kwargs
            self.assertIn("老铁 (@kol_tester)", call_kwargs["caption"])
            self.assertNotIn("好评评测", call_kwargs["caption"])
            self.assertNotIn("KOL 达人认证", call_kwargs["caption"])
            kb = call_kwargs["reply_markup"].inline_keyboard
            all_btn_texts = [b.text for row in kb for b in row]
            for t_val in all_btn_texts:
                self.assertNotIn("📖 查看", t_val)

    async def test_on_teacher_card_callback_swipe_same_photo_uses_caption(self):
        """Test that swiping between cards with identical photo uses instant caption edit without touching media."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "tc:swipe:1"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_caption = AsyncMock()
        update.callback_query.edit_message_media = AsyncMock()

        context = MagicMock()
        from bot.ui.teachers_card import DEFAULT_PLACEHOLDER_PHOTO
        context.user_data = {"current_card_photo": str(DEFAULT_PLACEHOLDER_PHOTO)}

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.count_teachers = AsyncMock(return_value=10)
            mock_db.search_teachers = AsyncMock(return_value=[{"id": 99, "name": "安安", "rating": 4.85}])
            mock_db.get_teacher_reviews = AsyncMock(return_value=[])

            await on_teacher_card_callback(update, context)

            update.callback_query.answer.assert_awaited_once()
            # Must edit caption only, zero media replacement!
            update.callback_query.edit_message_caption.assert_awaited_once()
            update.callback_query.edit_message_media.assert_not_called()

    async def test_on_teacher_card_callback_swipe_uses_cached_file_id(self):
        """Test that swiping to a new photo uses cached Telegram file_id if available."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "tc:swipe:2"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_media = AsyncMock()

        context = MagicMock()
        context.user_data = {"current_card_photo": "old_photo.jpg"}

        from bot.handlers.teachers import _PHOTO_FILE_ID_CACHE
        from bot.ui.teachers_card import DEFAULT_PLACEHOLDER_PHOTO
        _PHOTO_FILE_ID_CACHE[str(DEFAULT_PLACEHOLDER_PHOTO)] = "tg_file_id_abc123"

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.count_teachers = AsyncMock(return_value=10)
            mock_db.search_teachers = AsyncMock(return_value=[{"id": 99, "name": "安安", "rating": 4.85}])
            mock_db.get_teacher_reviews = AsyncMock(return_value=[])

            await on_teacher_card_callback(update, context)

            update.callback_query.answer.assert_awaited_once()
            update.callback_query.edit_message_media.assert_awaited_once()
            # Verify media used the cached string file_id rather than opening a file
            call_kwargs = update.callback_query.edit_message_media.call_args.kwargs
            self.assertEqual(call_kwargs["media"].media, "tg_file_id_abc123")

    async def test_on_teacher_card_callback_reviews_with_page(self):
        """Test rev callback with explicit page index formats and displays the correct page."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "tc:rev:99:2:1"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_caption = AsyncMock()

        context = MagicMock()

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.get_teacher = AsyncMock(return_value={
                "id": 99,
                "name": "安安",
                "rating": 4.85,
                "teacher_account": "@anan520",
                "teacher_post_link": "https://t.me/c/123/456",
                "photo_path": "photo.jpg",
            })
            mock_db.get_teacher_reviews = AsyncMock(return_value=[
                {"id": i, "content": f"评测内容 {i}", "date": 1788356740} for i in range(8)
            ])

            await on_teacher_card_callback(update, context)

            update.callback_query.answer.assert_awaited_once()
            mock_db.get_teacher.assert_awaited_once_with(99)
            mock_db.get_teacher_reviews.assert_awaited_once_with(99, limit=50)
            update.callback_query.edit_message_caption.assert_awaited_once()
            call_kwargs = update.callback_query.edit_message_caption.call_args.kwargs
            self.assertIn("2/2", call_kwargs["caption"])
            self.assertIn("7.", call_kwargs["caption"])
            self.assertIn("8.", call_kwargs["caption"])

    async def test_on_teacher_card_callback_reviews_overview(self):
        """Test rev callback displays reviews overview with compact metadata and no external detail buttons."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "tc:rev:99:2:0:0"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_caption = AsyncMock()

        context = MagicMock()

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.get_teacher = AsyncMock(return_value={
                "id": 99,
                "name": "安安",
                "rating": 4.85,
                "teacher_account": "@anan520",
                "teacher_post_link": "https://t.me/c/123/456",
                "photo_path": "photo.jpg",
            })
            mock_db.get_teacher_reviews = AsyncMock(return_value=[
                {
                    "id": 1,
                    "username": "tester",
                    "first_name": "张三",
                    "date": 1788356740,
                    "content": "安安老师技术超级棒！体验满分！",
                },
                {
                    "id": 2,
                    "username": "tester2",
                    "first_name": "李四",
                    "date": 1788356740,
                    "content": "还可以吧。",
                },
            ])

            await on_teacher_card_callback(update, context)

            update.callback_query.answer.assert_awaited_once()
            update.callback_query.edit_message_caption.assert_awaited_once()
            call_kwargs = update.callback_query.edit_message_caption.call_args.kwargs
            self.assertIn("张三 (@tester)", call_kwargs["caption"])
            self.assertIn("李四 (@tester2)", call_kwargs["caption"])
            self.assertNotIn("安安老师技术超级棒！", call_kwargs["caption"])
            self.assertNotIn("还可以吧。", call_kwargs["caption"])
            kb = call_kwargs["reply_markup"].inline_keyboard
            all_btn_texts = [b.text for row in kb for b in row]
            for t_val in all_btn_texts:
                self.assertNotIn("📖 查看", t_val)

    async def test_on_teacher_card_callback_rdtl(self):
        """Test rdtl callback opens single review detail subpage with full content and original post link."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "tc:rdtl:99:2:1:0:1"
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_caption = AsyncMock()

        context = MagicMock()

        with patch("bot.handlers.teachers.rate_limiter.is_callback_rate_limited", return_value=False), \
             patch("bot.handlers.teachers.db") as mock_db:
            mock_db.get_teacher = AsyncMock(return_value={
                "id": 99,
                "name": "安安",
                "rating": 4.85,
                "teacher_account": "@anan520",
                "teacher_post_link": "https://t.me/c/123/456",
                "photo_path": "photo.jpg",
            })
            mock_db.get_review = AsyncMock(return_value={
                "id": 1,
                "username": "tester",
                "first_name": "张三",
                "date": 1788356740,
                "content": "安安老师技术超级棒！体验满分！这是完整无删减的评测全文。",
                "message_link": "https://t.me/c/1622463102/9999",
                "chat_title": "精选评测群",
                "rating": 4.9,
            })

            await on_teacher_card_callback(update, context)

            update.callback_query.answer.assert_awaited_once()
            update.callback_query.edit_message_caption.assert_awaited_once()
            call_kwargs = update.callback_query.edit_message_caption.call_args.kwargs
            self.assertIn("安安老师技术超级棒！体验满分！这是完整无删减的评测全文。", call_kwargs["caption"])
            self.assertIn("【安安】· 评测全文 (#1)", call_kwargs["caption"])
            kb = call_kwargs["reply_markup"].inline_keyboard
            self.assertEqual(kb[0][0].url, "https://t.me/c/1622463102/9999")
            self.assertIn("查看评测原帖", kb[0][0].text)
            self.assertEqual(kb[1][0].callback_data, "tc:rev:99:2:0")
            self.assertIn("返回评测列表", kb[1][0].text)

    async def test_cmd_start_rdtl_deep_link(self):
        """Test /start rdtl_ deep link command directly opens review detail."""
        from bot.handlers.search import cmd_start
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_user.username = "test_user"
        update.effective_chat.id = 12345
        update.callback_query = None
        update.effective_message.reply_photo = AsyncMock()

        context = MagicMock()
        context.args = ["rdtl_99_1_2_0_1"]

        with patch("bot.handlers.search.db") as mock_db, \
             patch("bot.handlers.teachers.db") as mock_teacher_db:
            mock_db.register_user = AsyncMock()
            mock_teacher_db.get_teacher = AsyncMock(return_value={
                "id": 99,
                "name": "安安",
                "rating": 4.85,
                "photo_path": "photo.jpg",
            })
            mock_teacher_db.get_review = AsyncMock(return_value={
                "id": 1,
                "username": "tester",
                "first_name": "张三",
                "date": 1788356740,
                "content": "深度链接评测全文！",
                "message_link": "https://t.me/c/1622463102/9999",
                "chat_title": "精选评测群",
                "rating": 5.0,
            })

            await cmd_start(update, context)

            update.effective_message.reply_photo.assert_awaited_once()
            call_kwargs = update.effective_message.reply_photo.call_args.kwargs
            self.assertIn("深度链接评测全文！", call_kwargs["caption"])
            self.assertIn("【安安】· 评测全文 (#1)", call_kwargs["caption"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
