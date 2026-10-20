from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram import ReplyKeyboardRemove
from bot.inquiry.state import (
    InquirySession,
    InquiryStep,
    InquiryStateManager,
    inquiry_state_manager,
)
from bot.inquiry.rate_limiter import InquiryRateLimiter
from bot.inquiry.llm import generate_heuristic_search_query, generate_search_query, normalize_combo_key
from bot.inquiry.search import score_teacher_candidate, search_and_rank_teachers
from bot.inquiry.ui import (
    render_confirm_step,
    render_inquiry_summary,
    render_look_step,
    render_body_step,
    render_price_step,
    render_value_step,
    render_map_step,
    render_matched_teacher_card,
)
from bot.inquiry.handlers import (
    start_inquiry,
    on_inquiry_callback,
    on_inquiry_location,
    on_inquiry_text,
)


class TestInquiryState(unittest.TestCase):
    """Test session lifecycle, transitions, and TTL eviction for 4-question wizard."""

    def setUp(self):
        self.mgr = InquiryStateManager(ttl=1.0)
        self.sample_teacher = {
            "id": 10,
            "name": "菲菲",
            "city": "上海",
            "district": "静安",
            "price": 900.0,
            "teacher_account": "@feifei99",
        }

    def test_session_lifecycle(self):
        sess = self.mgr.create_session(
            user_id=123,
            chat_id=456,
            teacher_id=10,
            from_index=2,
            teacher=self.sample_teacher,
        )
        self.assertEqual(sess.user_id, 123)
        self.assertEqual(sess.step, InquiryStep.LOOK)
        self.assertEqual(sess.teacher_name, "菲菲")

        # Advance through steps
        self.mgr.update_step(123, InquiryStep.BODY)
        self.assertEqual(self.mgr.get_session(123).step, InquiryStep.BODY)

        self.mgr.update_step(123, InquiryStep.PRICE)
        self.assertEqual(self.mgr.get_session(123).step, InquiryStep.PRICE)

        self.mgr.update_step(123, InquiryStep.VALUE)
        self.assertEqual(self.mgr.get_session(123).step, InquiryStep.VALUE)

        self.mgr.update_step(123, InquiryStep.MAP)
        self.assertEqual(self.mgr.get_session(123).step, InquiryStep.MAP)

        # Clear session
        self.mgr.clear_session(123)
        self.assertIsNone(self.mgr.get_session(123))

    def test_session_ttl_expiration(self):
        self.mgr.create_session(
            user_id=999,
            chat_id=888,
            teacher_id=10,
            from_index=0,
            teacher=self.sample_teacher,
        )
        sess = self.mgr.get_session(999)
        self.assertIsNotNone(sess)

        # Simulate timeout
        sess.updated_at = time.time() - 2.0
        self.assertIsNone(self.mgr.get_session(999))


class TestInquiryRateLimiter(unittest.TestCase):
    """Test debouncing and daily quota enforcement."""

    def test_action_cooldown(self):
        limiter = InquiryRateLimiter(action_cooldown=0.5)
        self.assertFalse(limiter.is_action_limited(101))
        # Rapid second click
        self.assertTrue(limiter.is_action_limited(101))

    def test_submission_daily_and_burst_limits(self):
        limiter = InquiryRateLimiter(submission_cooldown=5.0, max_daily_submissions=2)
        limited, _ = limiter.is_submission_limited(202)
        self.assertFalse(limited)

        limiter.record_submission(202)

        # Burst check
        limited, reason = limiter.is_submission_limited(202)
        self.assertTrue(limited)
        self.assertIn("wait", reason.lower())

        # Simulate passing burst cooldown
        limiter._last_submission_time[202] = time.time() - 10.0
        limiter.record_submission(202)

        # Reached daily cap of 2
        limiter._last_submission_time[202] = time.time() - 10.0
        limited, reason = limiter.is_submission_limited(202)
        self.assertTrue(limited)
        self.assertIn("limit reached", reason.lower())


class TestInquirySearchAndQueryLLM(unittest.IsolatedAsyncioTestCase):
    """Test LLM query generation, dynamic weight re-ranking, and candidate sorting."""

    def setUp(self):
        self.session = InquirySession(
            user_id=1,
            chat_id=1,
            teacher_id=1,
            preferred_look="年轻稚嫩",
            preferred_body="高挑长腿",
            value_most="服务配合",
            latitude=31.23,
            longitude=121.47,
        )
        self.teacher_context = {
            "city": "上海",
            "district": "静安",
        }

    def test_heuristic_query_generator(self):
        out = generate_heuristic_search_query(self.session, self.teacher_context)
        self.assertEqual(out["source"], "heuristic")
        self.assertIn("年轻", out["keywords_list"])
        self.assertIn("长腿", out["keywords_list"])
        self.assertEqual(out["weight_focus"], "service")
        self.assertGreaterEqual(out["weights"]["service"], 0.4)
        self.assertEqual(out["city"], "上海")
        self.assertIn("加权", out["explanation"])

    @patch("bot.inquiry.llm._call_gemini", new_callable=AsyncMock)
    async def test_generate_search_query_mock_llm(self, mock_gemini):
        mock_gemini.return_value = {
            "keywords": "年轻 苗条",
            "weight_focus": "visual",
            "weights": {"visual": 0.5, "body": 0.2, "service": 0.2, "price": 0.1},
            "explanation": "重点检索年轻苗条老师，并加权颜值外观指标。",
        }
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "dummy_key", "EXTRACTOR_PROVIDER": "gemini", "DEEPSEEK_API_KEY": ""}):
            res = await generate_search_query(self.session, self.teacher_context)
            self.assertEqual(res["source"], "llm")
            self.assertEqual(res["weight_focus"], "visual")
            self.assertEqual(res["weights"]["visual"], 0.5)
            self.assertEqual(res["keywords_list"], ["年轻", "苗条"])

    @patch("bot.inquiry.llm._call_deepseek_or_openai", new_callable=AsyncMock)
    async def test_generate_search_query_mock_deepseek(self, mock_deepseek):
        mock_deepseek.return_value = {
            "keywords": "清纯 高挑",
            "weight_focus": "service",
            "weights": {"visual": 0.25, "body": 0.25, "service": 0.4, "price": 0.1},
            "explanation": "重点加权服务指标。",
        }
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "dummy_deepseek_key", "REVIEW_EXTRACTOR_PROVIDER": "deepseek"}):
            res = await generate_search_query(self.session, self.teacher_context)
            self.assertEqual(res["source"], "llm")
            self.assertEqual(res["weight_focus"], "service")
            self.assertEqual(res["weights"]["service"], 0.4)
            self.assertEqual(res["keywords_list"], ["清纯", "高挑"])

    def test_normalize_combo_key(self):
        # Exact canonical selections
        self.assertEqual(
            normalize_combo_key("青春嫩妹", "苗条纤细", "女友感"),
            "青春嫩妹|苗条纤细|女友感",
        )
        self.assertEqual(
            normalize_combo_key("成熟御姐", "高挑长腿", "颜值容貌"),
            "成熟御姐|高挑长腿|颜值容貌",
        )
        self.assertEqual(
            normalize_combo_key("不限风格", "不限身材", "综合均衡"),
            "不限风格|不限身材|综合均衡",
        )
        # Normalized aliases
        self.assertEqual(
            normalize_combo_key("嫩妹", "苗条", "综合体验"),
            "青春嫩妹|苗条纤细|综合均衡",
        )
        self.assertEqual(
            normalize_combo_key("清纯", "大胸", "性价比"),
            "清纯邻家|丰满有料|高性价比",
        )
        self.assertEqual(
            normalize_combo_key(None, "", None),
            "不限风格|不限身材|综合均衡",
        )
        # Custom typed input should return None (routing to LLM)
        self.assertIsNone(normalize_combo_key("混血超模", "高挑长腿", "女友感"))
        self.assertIsNone(normalize_combo_key("青春嫩妹", "欧美巨乳", "女友感"))
        self.assertIsNone(normalize_combo_key("青春嫩妹", "苗条纤细", "纯粹走心"))

    @patch("bot.inquiry.llm._call_gemini", new_callable=AsyncMock)
    @patch("bot.inquiry.llm._call_deepseek_or_openai", new_callable=AsyncMock)
    async def test_generate_search_query_predefined_combo(self, mock_deepseek, mock_gemini):
        # Predefined options should resolve directly from local json without invoking any LLM
        session = InquirySession(
            user_id=99,
            chat_id=99,
            teacher_id=1,
            preferred_look="青春嫩妹",
            preferred_body="苗条纤细",
            value_most="女友感",
        )
        res = await generate_search_query(session, {"city": "上海"})
        self.assertEqual(res["source"], "predefined")
        self.assertEqual(res["weight_focus"], "service")
        self.assertEqual(res["weights"]["service"], 0.55)
        self.assertIn("嫩妹", res["keywords_list"])
        self.assertIn("苗条", res["keywords_list"])
        self.assertIn("女友感", res["keywords_list"])
        self.assertEqual(res["city"], "上海")
        self.assertIn("女友感", res["explanation"])

        # Verify 0 LLM calls were made
        mock_gemini.assert_not_called()
        mock_deepseek.assert_not_called()

    def test_score_teacher_candidate(self):
        teacher_a = {
            "name": "可可",
            "tags": "年轻, 高挑长腿",
            "score_visual": 4.8,
            "score_body": 4.9,
            "score_service": 4.5,
            "price": 900,
        }
        teacher_b = {
            "name": "静静",
            "tags": "成熟, 丰满",
            "score_visual": 3.8,
            "score_body": 3.9,
            "score_service": 3.5,
            "price": 1500,
        }
        weights = {"visual": 0.4, "body": 0.4, "service": 0.1, "price": 0.1}
        keywords = ["年轻", "长腿"]

        score_a = score_teacher_candidate(teacher_a, keywords, weights)
        score_b = score_teacher_candidate(teacher_b, keywords, weights)

        # teacher_a matches tags and has higher visual/body scores
        self.assertGreater(score_a, score_b)

    def test_score_teacher_candidate_with_location_text(self):
        teacher_jingan = {
            "name": "静安老师",
            "district": "静安",
            "score_visual": 4.0,
            "score_body": 4.0,
            "score_service": 4.0,
        }
        teacher_pudong = {
            "name": "浦东老师",
            "district": "浦东",
            "score_visual": 4.0,
            "score_body": 4.0,
            "score_service": 4.0,
        }
        weights = {"visual": 0.3, "body": 0.3, "service": 0.4}
        score_j = score_teacher_candidate(teacher_jingan, [], weights, location_text="静安区")
        score_p = score_teacher_candidate(teacher_pudong, [], weights, location_text="静安区")
        self.assertGreater(score_j, score_p)

    async def test_search_and_rank_teachers(self):
        mock_db = MagicMock()
        mock_db.search_teachers = AsyncMock(return_value=[
            {
                "id": 1,
                "name": "低分候选",
                "tags": "常规",
                "score_visual": 3.0,
                "score_body": 3.0,
                "score_service": 3.0,
            },
            {
                "id": 2,
                "name": "高分年轻候选",
                "tags": "年轻, 高挑长腿",
                "score_visual": 4.9,
                "score_body": 4.9,
                "score_service": 5.0,
            },
        ])
        query_info = {
            "keywords_list": ["年轻", "长腿"],
            "weights": {"visual": 0.3, "body": 0.3, "service": 0.3, "price": 0.1},
            "weight_focus": "service",
            "city": "上海",
        }
        results = await search_and_rank_teachers(mock_db, query_info)
        self.assertEqual(len(results), 2)
        # Verify higher scoring candidate is ranked first
        self.assertEqual(results[0]["id"], 2)


class TestInquiryUI(unittest.TestCase):
    """Test UI rendering for the 4 questions (look, body, value, map) and matched teacher card."""

    def setUp(self):
        self.teacher = {
            "id": 5,
            "name": "菲菲",
            "city": "上海",
            "district": "静安",
            "price": 1000.0,
            "teacher_account": "@feifei",
            "score_service": 4.9,
        }
        self.session = InquirySession(user_id=1, chat_id=1, teacher_id=5)

    def test_render_look_step(self):
        text, markup = render_look_step(self.teacher, self.session)
        self.assertIn("第 1/5 题：外貌风格", text)
        self.assertIn("菲菲", text)
        kb = markup.inline_keyboard
        self.assertEqual(kb[0][0].callback_data, "inq:look:青春嫩妹")
        self.assertEqual(kb[0][1].callback_data, "inq:look:成熟御姐")
        self.assertEqual(kb[1][0].callback_data, "inq:look:清纯邻家")

    def test_render_body_step(self):
        self.session.preferred_look = "年轻稚嫩"
        text, markup = render_body_step(self.teacher, self.session)
        self.assertIn("第 2/5 题：身材体型", text)
        # Verify in-chat answer is an HTML edit link
        self.assertIn('start=inq_look', text)
        self.assertIn('年轻稚嫩 ✏️', text)
        kb = markup.inline_keyboard
        # No extra edit buttons on keyboard; only option choices
        self.assertEqual(kb[0][0].callback_data, "inq:body:苗条纤细")
        self.assertEqual(kb[0][1].callback_data, "inq:body:丰满有料")
        self.assertEqual(kb[1][0].callback_data, "inq:body:高挑长腿")
        self.assertEqual(kb[1][1].callback_data, "inq:body:微胖肉感")
        self.assertEqual(kb[2][0].callback_data, "inq:body:娇小可爱")
        self.assertEqual(kb[2][1].callback_data, "inq:body:不限身材")

    def test_render_price_step(self):
        self.session.preferred_look = "年轻稚嫩"
        self.session.preferred_body = "高挑长腿"
        text, markup = render_price_step(self.teacher, self.session)
        self.assertIn("第 3/5 题：单次预算 · 1P", text)
        self.assertIn("300 梯度", text)
        self.assertIn('start=inq_look', text)
        self.assertIn('start=inq_body', text)
        kb = markup.inline_keyboard
        self.assertEqual(kb[0][0].callback_data, "inq:price:600以下(1P)")
        self.assertEqual(kb[0][1].callback_data, "inq:price:600-900(1P)")
        self.assertEqual(kb[1][0].callback_data, "inq:price:900-1200(1P)")
        self.assertEqual(kb[1][1].callback_data, "inq:price:1200-1500(1P)")
        self.assertEqual(kb[2][0].callback_data, "inq:price:1500-1800(1P)")
        self.assertEqual(kb[2][1].callback_data, "inq:price:1800以上(1P)")
        self.assertEqual(kb[3][0].callback_data, "inq:price:不限预算")

    def test_render_value_step(self):
        self.session.preferred_look = "年轻稚嫩"
        self.session.preferred_body = "高挑长腿"
        self.session.preferred_price = "900-1200(1P)"
        text, markup = render_value_step(self.teacher, self.session)
        self.assertIn("第 4/5 题：核心侧重点", text)
        # Verify in-chat answers are HTML edit links
        self.assertIn('start=inq_look', text)
        self.assertIn('start=inq_body', text)
        self.assertIn('start=inq_price', text)
        kb = markup.inline_keyboard
        # No extra edit buttons on keyboard; only option choices
        self.assertEqual(kb[0][0].callback_data, "inq:val:服务配合")
        self.assertEqual(kb[0][1].callback_data, "inq:val:女友感")
        self.assertEqual(kb[1][0].callback_data, "inq:val:颜值容貌")
        self.assertEqual(kb[1][1].callback_data, "inq:val:身材体态")
        self.assertEqual(kb[2][0].callback_data, "inq:val:高性价比")
        self.assertEqual(kb[2][1].callback_data, "inq:val:综合均衡")

    def test_render_confirm_step(self):
        self.session.preferred_look = "年轻稚嫩"
        self.session.preferred_body = "高挑长腿"
        self.session.preferred_price = "900-1200(1P)"
        self.session.value_most = "服务配合"
        self.session.latitude = 31.23
        self.session.longitude = 121.47
        text, markup = render_confirm_step(self.teacher, self.session)
        self.assertIn("需求定制确认清单", text)
        # Verify in-chat answers are HTML edit links
        self.assertIn('start=inq_look', text)
        self.assertIn('start=inq_body', text)
        self.assertIn('start=inq_price', text)
        self.assertIn('start=inq_val', text)
        self.assertIn('start=inq_map', text)
        self.assertIn("年轻稚嫩 ✏️", text)
        self.assertIn("高挑长腿 ✏️", text)
        self.assertIn("900-1200(1P) ✏️", text)
        self.assertIn("服务配合 ✏️", text)
        self.assertIn("单次预算(1P)", text)
        kb = markup.inline_keyboard
        # Keyboard only has submit and cancel buttons
        self.assertEqual(kb[0][0].callback_data, "inq:submit")
        self.assertEqual(kb[1][0].callback_data, "inq:cancel")

    def test_render_confirm_step_with_custom_location_text(self):
        self.session.preferred_look = "清纯甜美"
        self.session.preferred_body = "苗条"
        self.session.preferred_price = "800以下"
        self.session.value_most = "性价比"
        self.session.latitude = None
        self.session.longitude = None
        self.session.location_text = "静安区"
        text, markup = render_confirm_step(self.teacher, self.session)
        self.assertIn("静安区 ✏️", text)
        self.assertIn('start=inq_map', text)
        self.assertIn('start=inq_price', text)

    def test_render_map_step(self):
        text, markup = render_map_step(self.teacher, self.session)
        self.assertIn("第 5/5 题：设置地理位置", text)
        self.assertIn("预算(1P)", text)
        kb = markup.keyboard
        self.assertTrue(kb[0][0].request_location)
        self.assertEqual([b.text for b in kb[1]], ["浦东", "闵行", "普陀"])
        self.assertEqual([b.text for b in kb[2]], ["静安", "徐汇", "长宁"])
        self.assertIn("跳过位置", kb[3][0].text)

    def test_render_steps_without_target_teacher(self):
        """Test wizard steps rendering cleanly when launched from homepage without target teacher."""
        empty_sess = InquirySession(user_id=1, chat_id=1, teacher_id=0)
        # Look step
        text, _ = render_look_step(None, empty_sess)
        self.assertNotIn("目标老师", text)
        self.assertIn("第 1/5 题：外貌风格", text)

        # Map step
        text, _ = render_map_step(None, empty_sess)
        self.assertNotIn("目标老师", text)
        self.assertNotIn("常驻参考", text)
        self.assertIn("第 5/5 题：设置地理位置", text)

    def test_render_matched_teacher_card(self):
        query_info = {
            "weight_focus": "service",
            "explanation": "加权服务配合排位",
        }
        text, markup = render_matched_teacher_card(self.teacher, index=0, total=3, query_info=query_info)
        self.assertIn("AI 偏好定制推荐（第 1 / 3 位）", text)
        self.assertIn("加权服务配合排位", text)
        self.assertIn("菲菲", text)
        self.assertIn("服务配合", text)

        kb = markup.inline_keyboard
        # Row 1: Next button
        self.assertEqual(kb[0][0].callback_data, "inq:swipe:1")
        # Row 2: Contact
        self.assertIn("https://t.me/feifei", kb[1][0].url)
        # Row 3: Reviews button preserves inquiry flow
        self.assertEqual(kb[2][0].callback_data, "inq:rev:5:0")
        # Row 4: Summary report button
        self.assertEqual(kb[3][0].callback_data, "inq:summary:0")
        # Row 5: Restart
        self.assertEqual(kb[4][0].callback_data, "inq:restart:5:0")

    def test_render_inquiry_summary(self):
        self.session.preferred_look = "清纯初恋脸"
        self.session.preferred_body = "高挑纤细"
        self.session.value_most = "服务配合"
        self.session.location_text = "静安区"
        query_info = {
            "keywords": "年轻 苗条",
            "weight_focus": "service",
            "weights": {"visual": 0.2, "body": 0.2, "service": 0.5, "price": 0.1},
            "explanation": "重点加权服务配合",
            "source": "llm",
        }
        text, markup = render_inquiry_summary(self.session, query_info, total_matched=20)
        self.assertIn("AI 智能匹配总结报告", text)
        self.assertIn("清纯初恋脸", text)
        self.assertIn("高挑纤细", text)
        self.assertIn("服务配合", text)
        self.assertIn("静安区", text)
        self.assertIn("#年轻 #苗条", text)
        self.assertIn("【服务配合】", text)
        self.assertIn("服务 50%", text)
        self.assertIn("20", text)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "inq:swipe:0")

    def test_render_inquiry_summary_predefined(self):
        self.session.preferred_look = "青春嫩妹"
        self.session.preferred_body = "苗条纤细"
        self.session.value_most = "女友感"
        self.session.location_skipped = True
        query_info = {
            "keywords": "嫩妹 苗条 女友感",
            "weight_focus": "service",
            "weights": {"visual": 0.2, "body": 0.15, "service": 0.55, "price": 0.1},
            "explanation": "已锁定青春嫩妹与苗条身材特征，大幅强化女友感与情绪陪伴服务权重。",
            "source": "predefined",
        }
        text, markup = render_inquiry_summary(self.session, query_info, total_matched=12)
        self.assertIn("AI 智能匹配总结报告", text)
        self.assertIn("AI 大模型深度解析结果", text)
        self.assertIn("#嫩妹 #苗条 #女友感", text)
        self.assertIn("服务 55%", text)
        self.assertIn("12", text)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "inq:swipe:0")


class TestInquiryHandlers(unittest.IsolatedAsyncioTestCase):
    """Test handler dispatching, wizard transitions, search ranking execution, and swipe navigation."""

    def setUp(self):
        self.teacher_1 = {
            "id": 7,
            "name": "可可",
            "city": "北京",
            "district": "朝阳",
            "price": 1200.0,
            "teacher_account": "@koko_bj",
            "photo_path": None,
        }
        self.teacher_2 = {
            "id": 8,
            "name": "依依",
            "city": "北京",
            "district": "海淀",
            "price": 1000.0,
            "teacher_account": "@yiyi_bj",
            "photo_path": None,
        }

    @patch("bot.inquiry.handlers.db")
    async def test_start_inquiry_flow(self, mock_db):
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_1)

        update = MagicMock()
        update.effective_user.id = 555
        update.effective_chat.id = 666
        update.callback_query = MagicMock()
        update.callback_query.message.photo = None
        update.callback_query.message.message_id = 99
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}

        await start_inquiry(update, context, teacher_id=7, from_index=1)

        mock_db.get_teacher.assert_awaited_once_with(7)
        update.callback_query.edit_message_text.assert_awaited_once()
        self.assertTrue(context.user_data.get("inquiry_active"))

    @patch("bot.inquiry.handlers.inquiry_rate_limiter.is_action_limited", return_value=False)
    @patch("bot.inquiry.handlers.db")
    async def test_full_wizard_callback_progression(self, mock_db, mock_limiter):
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_1)
        mock_db.search_teachers = AsyncMock(return_value=[self.teacher_1, self.teacher_2])

        session = inquiry_state_manager.create_session(
            user_id=777,
            chat_id=888,
            teacher_id=7,
            from_index=0,
            teacher=self.teacher_1,
        )

        update = MagicMock()
        update.effective_user.id = 777
        update.effective_chat.id = 888
        update.callback_query = MagicMock()
        update.callback_query.message = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.user_data = {}
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=101))

        # Question #1 (Look) -> Question #2 (Body)
        update.callback_query.data = "inq:look:成熟御姐"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.preferred_look, "成熟御姐")
        self.assertEqual(session.step, InquiryStep.BODY)

        # Question #2 (Body) -> Question #3 (Price Range)
        update.callback_query.data = "inq:body:高挑长腿"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.preferred_body, "高挑长腿")
        self.assertEqual(session.step, InquiryStep.PRICE)

        # Question #3 (Price Range) -> Question #4 (Value Most)
        update.callback_query.data = "inq:price:800-1200"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.preferred_price, "800-1200")
        self.assertEqual(session.step, InquiryStep.VALUE)

        # Question #4 (Value Most) -> Question #5 (Map Pin)
        update.callback_query.data = "inq:val:服务配合"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.value_most, "服务配合")
        self.assertEqual(session.step, InquiryStep.MAP)
        context.bot.send_message.assert_awaited_once()

        # Question #5 (Map Pin received via location update) -> Transition to CONFIRMED
        loc_update = MagicMock()
        loc_update.effective_user.id = 777
        loc_update.effective_chat.id = 888
        loc_update.callback_query = None
        loc_update.message.location.latitude = 39.904
        loc_update.message.location.longitude = 116.407
        loc_update.message.reply_text = AsyncMock(return_value=MagicMock(message_id=102))
        loc_update.effective_message.reply_text = loc_update.message.reply_text

        await on_inquiry_location(loc_update, context)

        # Confirm step reached and confirmed_once set to True
        self.assertEqual(session.step, InquiryStep.CONFIRMED)
        self.assertTrue(session.confirmed_once)

        # User clicks Submit on confirmation screen
        update.callback_query.data = "inq:submit"
        await on_inquiry_callback(update, context)

        # Matched teacher results stored in context.user_data for swiping
        self.assertIn("inquiry_matched_ids", context.user_data)
        self.assertEqual(len(context.user_data["inquiry_matched_ids"]), 2)
        # Active wizard session evicted
        self.assertIsNone(inquiry_state_manager.get_session(777))

    @patch("bot.inquiry.handlers.db")
    async def test_wizard_with_typed_custom_answers(self, mock_db):
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_1)
        mock_db.search_teachers = AsyncMock(return_value=[self.teacher_1])

        session = inquiry_state_manager.create_session(
            user_id=333,
            chat_id=444,
            teacher_id=7,
            from_index=0,
            teacher=self.teacher_1,
        )

        update = MagicMock()
        update.effective_user.id = 333
        update.effective_chat.id = 444
        update.callback_query = None
        update.message.reply_text = AsyncMock()
        update.effective_message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.user_data = {"inquiry_active": True}

        # User types custom look
        update.message.text = "清纯初恋脸"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertEqual(session.preferred_look, "清纯初恋脸")
        self.assertEqual(session.step, InquiryStep.BODY)

        # User types custom body
        update.message.text = "极品身材微丰满"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertEqual(session.preferred_body, "极品身材微丰满")
        self.assertEqual(session.step, InquiryStep.PRICE)

        # User attempts to type arbitrary free-text at Question #3 (Price) -> RESTRICTED!
        update.message.text = "随意给点不要太贵"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertEqual(session.step, InquiryStep.PRICE)  # Stays on price step
        self.assertIsNone(session.preferred_price)

        # User types valid select range at Question #3 (Price)
        update.message.text = "900-1200"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertEqual(session.preferred_price, "900-1200(1P)")
        self.assertEqual(session.step, InquiryStep.VALUE)

        # User types custom priority at Question #4
        update.message.text = "注重卫生与不催钟"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertEqual(session.value_most, "注重卫生与不催钟")
        self.assertEqual(session.step, InquiryStep.MAP)

        # User types skip location at Question #4 -> transitions to CONFIRMED
        update.message.text = "跳过位置"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertTrue(session.location_skipped)
        self.assertEqual(session.step, InquiryStep.CONFIRMED)
        self.assertTrue(session.confirmed_once)

        # User submits confirmation
        cb_update = MagicMock()
        cb_update.effective_user.id = 333
        cb_update.effective_chat.id = 444
        cb_update.callback_query = MagicMock()
        cb_update.callback_query.data = "inq:submit"
        cb_update.callback_query.message.photo = None
        cb_update.callback_query.edit_message_text = AsyncMock()
        with patch("bot.inquiry.handlers.generate_search_query", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {
                "keywords": "年轻 苗条",
                "keywords_list": ["年轻", "苗条"],
                "weight_focus": "service",
                "weights": {"visual": 0.25, "body": 0.25, "service": 0.35, "price": 0.15},
                "explanation": "匹配测试",
                "source": "llm",
            }
            await on_inquiry_callback(cb_update, context)

        self.assertIn("inquiry_matched_ids", context.user_data)
        self.assertIn("inquiry_summary_data", context.user_data)
        cb_update.callback_query.edit_message_text.assert_awaited_once()
        summary_call = cb_update.callback_query.edit_message_text.call_args.kwargs
        self.assertIn("AI 智能匹配总结报告", summary_call["text"])
        self.assertEqual(summary_call["reply_markup"].inline_keyboard[0][0].callback_data, "inq:swipe:0")

    @patch("bot.inquiry.handlers.db")
    async def test_wizard_with_typed_custom_location_text(self, mock_db):
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_1)
        mock_db.search_teachers = AsyncMock(return_value=[self.teacher_1])

        session = inquiry_state_manager.create_session(
            user_id=555,
            chat_id=666,
            teacher_id=7,
            from_index=0,
            teacher=self.teacher_1,
        )

        update = MagicMock()
        update.effective_user.id = 555
        update.effective_chat.id = 666
        update.callback_query = None
        update.message.reply_text = AsyncMock()
        update.effective_message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.user_data = {"inquiry_active": True}

        # Step 1: Look
        update.message.text = "甜美可爱"
        await on_inquiry_text(update, context)

        # Step 2: Body
        update.message.text = "苗条身材"
        await on_inquiry_text(update, context)

        # Step 3: Price
        update.message.text = "600-900 (1P)"
        await on_inquiry_text(update, context)
        self.assertEqual(session.preferred_price, "600-900(1P)")

        # Step 4: Value
        update.message.text = "态度温柔"
        await on_inquiry_text(update, context)
        self.assertEqual(session.step, InquiryStep.MAP)

        # Step 5: Type custom location string (e.g. "静安寺附近")
        update.message.text = "静安寺附近"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertEqual(session.location_text, "静安寺附近")
        self.assertIsNone(session.latitude)
        self.assertIsNone(session.longitude)
        self.assertFalse(session.location_skipped)
        self.assertEqual(session.step, InquiryStep.CONFIRMED)
        self.assertTrue(session.confirmed_once)

        # Check that ReplyKeyboardRemove was sent in one of the replies
        reply_calls = update.message.reply_text.call_args_list
        has_reply_remove = any(
            isinstance(call.kwargs.get("reply_markup"), ReplyKeyboardRemove)
            for call in reply_calls
        )
        self.assertTrue(has_reply_remove)

        # Check confirmation message includes the typed location
        last_call_text = reply_calls[-1].kwargs.get("text", "")
        self.assertIn("静安寺附近 ✏️", last_call_text)

        # Verify subsequently sending GPS pin clears location_text
        session.step = InquiryStep.MAP
        loc_update = MagicMock()
        loc_update.effective_user.id = 555
        loc_update.effective_chat.id = 666
        loc_update.message.location.latitude = 31.22
        loc_update.message.location.longitude = 121.45
        loc_update.message.reply_text = AsyncMock()
        await on_inquiry_location(loc_update, context)
        self.assertEqual(session.latitude, 31.22)
        self.assertIsNone(session.location_text)

        # Verify typing "跳过位置" clears location_text
        session.step = InquiryStep.MAP
        session.location_text = "静安寺"
        update.message.text = "跳过位置"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertTrue(session.location_skipped)
        self.assertIsNone(session.location_text)

    @patch("bot.inquiry.handlers.inquiry_rate_limiter.is_action_limited", return_value=False)
    @patch("bot.inquiry.handlers.db")
    async def test_wizard_answer_redirect_and_edit(self, mock_db, mock_limiter):
        """Test jumping back to edit previous answers during wizard and from confirmation review."""
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_1)
        session = inquiry_state_manager.create_session(
            user_id=111,
            chat_id=222,
            teacher_id=7,
            teacher=self.teacher_1,
        )

        update = MagicMock()
        update.effective_user.id = 111
        update.effective_chat.id = 222
        update.callback_query = MagicMock()
        update.callback_query.message = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.user_data = {}
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=202))

        # 1. Answer Look -> Step BODY
        update.callback_query.data = "inq:look:年轻稚嫩"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.BODY)
        self.assertEqual(session.preferred_look, "年轻稚嫩")

        # 2. Click redirect button to re-edit look (inq:goto:look)
        update.callback_query.data = "inq:goto:look"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.LOOK)

        # 3. Change look to 成熟御姐 -> advances to BODY since confirmed_once is False
        update.callback_query.data = "inq:look:成熟御姐"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.BODY)
        self.assertEqual(session.preferred_look, "成熟御姐")

        # 4. Answer body, price, and value
        update.callback_query.data = "inq:body:高挑长腿"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.PRICE)

        update.callback_query.data = "inq:price:900-1200(1P)"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.VALUE)
        self.assertEqual(session.preferred_price, "900-1200(1P)")

        update.callback_query.data = "inq:val:高性价比"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.MAP)

        # 5. Skip location via text -> reaches CONFIRMED
        text_update = MagicMock()
        text_update.effective_user.id = 111
        text_update.effective_chat.id = 222
        text_update.callback_query = None
        text_update.message.text = "跳过位置"
        text_update.message.reply_text = AsyncMock()
        await on_inquiry_text(text_update, context)
        self.assertEqual(session.step, InquiryStep.CONFIRMED)
        self.assertTrue(session.confirmed_once)

        # 6. From confirmation screen, click inq:goto:val to re-edit value
        update.callback_query.data = "inq:goto:val"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.VALUE)

        # 7. Change value to 颜值容貌 -> since confirmed_once is True, returns directly to CONFIRMED!
        update.callback_query.data = "inq:val:颜值容貌"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.CONFIRMED)
        self.assertEqual(session.value_most, "颜值容貌")

        # 8. Test inq:goto:confirm directly
        update.callback_query.data = "inq:goto:body"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.BODY)

        update.callback_query.data = "inq:goto:confirm"
        await on_inquiry_callback(update, context)
        self.assertEqual(session.step, InquiryStep.CONFIRMED)

    @patch("bot.inquiry.handlers.inquiry_rate_limiter.is_action_limited", return_value=False)
    @patch("bot.inquiry.handlers.db")
    async def test_inquiry_swipe_callback(self, mock_db, mock_limiter):
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_2)

        update = MagicMock()
        update.effective_user.id = 777
        update.effective_chat.id = 888
        update.callback_query = MagicMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_media = AsyncMock()
        update.callback_query.edit_message_caption = AsyncMock()

        context = MagicMock()
        context.user_data = {
            "inquiry_matched_ids": [7, 8],
            "inquiry_query_info": {"weight_focus": "service", "explanation": "服务加权"},
        }

        # Swipe to index 1
        update.callback_query.data = "inq:swipe:1"
        await on_inquiry_callback(update, context)

        mock_db.get_teacher.assert_awaited_once_with(8)
        update.callback_query.edit_message_media.assert_awaited_once()

    @patch("bot.inquiry.handlers.db")
    async def test_start_inquiry_from_homepage_callback(self, mock_db):
        """Test user clicking [ 🎯 需求定制 ] on homepage triggers inquiry without a teacher_id using real rate limiter."""
        update = MagicMock()
        update.effective_user.id = 1234
        update.effective_chat.id = 5678
        update.callback_query = MagicMock()
        update.callback_query.data = "inq:start"
        update.callback_query.message.photo = None
        update.callback_query.message.message_id = 111
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}

        await on_inquiry_callback(update, context)

        # Confirm DB teacher was NOT queried since no teacher_id was provided
        mock_db.get_teacher.assert_not_called()
        update.callback_query.edit_message_text.assert_awaited_once()
        self.assertTrue(context.user_data.get("inquiry_active"))

        # Confirm active session exists at LOOK step
        session = inquiry_state_manager.get_session(1234)
        self.assertIsNotNone(session)
        self.assertEqual(session.step, InquiryStep.LOOK)
        self.assertEqual(session.teacher_id, 0)
        self.assertEqual(session.teacher_name, "")

    @patch("bot.inquiry.handlers.db")
    async def test_inquiry_deeplink_and_chat_commands(self, mock_db):
        """Test deep links (e.g. /start inq_look) and in-chat slash commands (/edit_body)."""
        from bot.inquiry.handlers import handle_inquiry_deeplink
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_1)
        session = inquiry_state_manager.create_session(
            user_id=555,
            chat_id=666,
            teacher_id=7,
            teacher=self.teacher_1,
        )

        update = MagicMock()
        update.effective_user.id = 555
        update.effective_chat.id = 666
        update.effective_message.reply_text = AsyncMock()
        update.message = update.effective_message
        context = MagicMock()
        context.user_data = {}

        # 1. Trigger deep link for Question #2 (body)
        await handle_inquiry_deeplink(update, context, "inq_body")
        self.assertEqual(session.step, InquiryStep.BODY)
        update.effective_message.reply_text.assert_awaited()

        # 2. Trigger in-chat command /edit_val
        update.message.text = "/edit_val"
        handled = await on_inquiry_text(update, context)
        self.assertTrue(handled)
        self.assertEqual(session.step, InquiryStep.VALUE)

        # 3. Trigger deep link for confirm
        await handle_inquiry_deeplink(update, context, "inq_confirm")
        self.assertEqual(session.step, InquiryStep.CONFIRMED)

    @patch("bot.inquiry.handlers.inquiry_rate_limiter.is_action_limited", return_value=False)
    @patch("bot.inquiry.handlers.db")
    async def test_inquiry_rev_and_back_to_swipe_preserves_matches(self, mock_db, mock_limiter):
        """Test clicking reviews from inquiry card and returning preserves matched 20 teachers."""
        mock_db.get_teacher = AsyncMock(return_value=self.teacher_1)
        mock_db.get_teacher_reviews = AsyncMock(return_value=[
            {
                "id": 101,
                "first_name": "张三",
                "username": "zhangsan",
                "chat_title": "评测群",
                "date": 1672531199,
                "content": "老师服务态度很好",
            }
        ])

        update = MagicMock()
        update.effective_user.id = 555
        update.effective_chat.id = 666
        update.callback_query = MagicMock()
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_caption = AsyncMock()
        update.callback_query.edit_message_media = AsyncMock()

        context = MagicMock()
        context.user_data = {
            "inquiry_matched_ids": [7, 8, 9],
            "inquiry_query_info": {
                "keywords": "年轻",
                "weight_focus": "service",
                "explanation": "匹配推荐",
            },
        }

        # 1. User clicks reviews button on inquiry teacher card (inq:rev:7:0)
        update.callback_query.data = "inq:rev:7:0"
        await on_inquiry_callback(update, context)

        update.callback_query.edit_message_caption.assert_awaited_once()
        call_kwargs = update.callback_query.edit_message_caption.call_args.kwargs
        rev_text = call_kwargs["caption"]
        rev_markup = call_kwargs["reply_markup"]

        self.assertIn("全部评测", rev_text)
        # Verify "返回老师卡片" returns to inq:swipe:0 instead of global tc:swipe
        back_btn = rev_markup.inline_keyboard[-1][0]
        self.assertEqual(back_btn.callback_data, "inq:swipe:0")
        self.assertIn("返回老师卡片", back_btn.text)

        # 2. Simulate clicking "返回老师卡片" (inq:swipe:0)
        update.callback_query.data = "inq:swipe:0"
        await on_inquiry_callback(update, context)

        update.callback_query.edit_message_media.assert_awaited_once()
        media_obj = update.callback_query.edit_message_media.call_args.kwargs["media"]
        card_text = media_obj.caption
        # Verified: returns to matched card 1 of 3
        self.assertIn("AI 偏好定制推荐（第 1 / 3 位）", card_text)
        self.assertEqual(context.user_data["inquiry_matched_ids"], [7, 8, 9])

    def test_homepage_menu_markup_contains_inquiry_button(self):
        """Test that browse menu markup contains the 需求定制 button pointing to inq:start."""
        from bot.ui.menu_markup import _browse_menu_markup
        state = {
            "active_picker": None,
            "service": [],
            "city": None,
            "district": [],
            "price_idx": None,
        }
        markup = _browse_menu_markup(state, lang="zh")
        button_callbacks = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data
        ]
        self.assertIn("inq:start", button_callbacks)

    @patch("bot.inquiry.handlers.inquiry_rate_limiter.is_action_limited", return_value=False)
    @patch("bot.inquiry.handlers.inquiry_rate_limiter.is_submission_limited", return_value=(False, ""))
    @patch("bot.inquiry.handlers.db")
    async def test_inquiry_single_summary_response_and_summary_toggle(self, mock_db, mock_sub_limiter, mock_act_limiter):
        """Test submitting inquiry produces exactly ONE response (summary report) and toggling summary works."""
        mock_db.get_teacher = AsyncMock(side_effect=lambda tid: self.teacher_1 if tid == 7 else self.teacher_2)
        mock_db.search_teachers = AsyncMock(return_value=[self.teacher_1, self.teacher_2])

        session = inquiry_state_manager.create_session(
            user_id=777,
            chat_id=888,
            teacher_id=7,
            teacher=self.teacher_1,
        )
        session.preferred_look = "清纯初恋脸"
        session.preferred_body = "高挑纤细"
        session.value_most = "服务配合"
        session.location_skipped = True
        session.step = InquiryStep.CONFIRMED

        update = MagicMock()
        update.effective_user.id = 777
        update.effective_chat.id = 888
        update.callback_query = MagicMock()
        update.callback_query.data = "inq:submit"
        update.callback_query.message.photo = None
        update.callback_query.message.delete = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}
        context.bot.send_photo = AsyncMock()
        context.bot.send_message = AsyncMock()

        # 1. User submits inquiry -> Exactly 1 response: Summary Report
        with patch("bot.inquiry.handlers.generate_search_query", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {
                "keywords": "清纯 高挑",
                "keywords_list": ["清纯", "高挑"],
                "weight_focus": "service",
                "weights": {"visual": 0.25, "body": 0.25, "service": 0.35, "price": 0.15},
                "explanation": "匹配测试",
                "source": "llm",
            }
            await on_inquiry_callback(update, context)

        # Verified: edit_message_text called once with summary
        update.callback_query.edit_message_text.assert_awaited_once()
        summary_call = update.callback_query.edit_message_text.call_args.kwargs
        summary_text = summary_call["text"]
        summary_markup = summary_call["reply_markup"]

        self.assertIn("AI 智能匹配总结报告", summary_text)
        self.assertIn("清纯初恋脸", summary_text)
        # Verified: NO extra messages sent (not 2 answers)
        context.bot.send_photo.assert_not_called()
        context.bot.send_message.assert_not_called()

        # Check button on summary report points to card #1 (index 0)
        browse_btn = summary_markup.inline_keyboard[0][0]
        self.assertEqual(browse_btn.callback_data, "inq:swipe:0")
        self.assertIn("立即浏览推荐老师 (1/2) ➔", browse_btn.text)

        # 2. User clicks browse button (inq:swipe:0) from the text summary report
        update.callback_query.data = "inq:swipe:0"
        await on_inquiry_callback(update, context)

        # Verified: deletes text message and sends Teacher #1 photo card
        update.callback_query.message.delete.assert_awaited_once()
        context.bot.send_photo.assert_awaited_once()
        photo_call = context.bot.send_photo.call_args.kwargs
        card_text = photo_call["caption"]
        card_markup = photo_call["reply_markup"]
        self.assertIn("可可", card_text)
        self.assertIn("AI 偏好定制推荐（第 1 / 2 位）", card_text)

        # Check Row 4 button is "查看需求与 AI 总结" pointing to inq:summary:0
        summary_btn = card_markup.inline_keyboard[3][0]
        self.assertEqual(summary_btn.callback_data, "inq:summary:0")
        self.assertIn("查看需求与 AI 总结", summary_btn.text)

        # 3. User clicks "查看需求与 AI 总结" (inq:summary:0) from the photo card
        update.callback_query.message.photo = [MagicMock()]
        update.callback_query.edit_message_caption = AsyncMock()
        update.callback_query.edit_message_media = AsyncMock()
        update.callback_query.data = "inq:summary:0"
        await on_inquiry_callback(update, context)

        # Verified: edits caption into summary report with return button pointing back to card #1
        update.callback_query.edit_message_caption.assert_awaited_once()
        sum2_call = update.callback_query.edit_message_caption.call_args.kwargs
        sum2_markup = sum2_call["reply_markup"]
        return_btn = sum2_markup.inline_keyboard[0][0]
        self.assertEqual(return_btn.callback_data, "inq:swipe:0")
        self.assertIn("立即浏览推荐老师 (1/2) ➔", return_btn.text)

        # 4. User swipes to Teacher #2 (inq:swipe:1)
        update.callback_query.data = "inq:swipe:1"
        await on_inquiry_callback(update, context)

        update.callback_query.edit_message_media.assert_awaited_once()
        card2_media = update.callback_query.edit_message_media.call_args.kwargs["media"]
        card2_markup = update.callback_query.edit_message_media.call_args.kwargs["reply_markup"]
        self.assertIn("依依", card2_media.caption)
        summary2_btn = card2_markup.inline_keyboard[3][0]
        self.assertEqual(summary2_btn.callback_data, "inq:summary:1")

        # 5. From Teacher #2, click summary button (inq:summary:1)
        update.callback_query.edit_message_caption.reset_mock()
        update.callback_query.data = "inq:summary:1"
        await on_inquiry_callback(update, context)

        update.callback_query.edit_message_caption.assert_awaited_once()
        sum3_call = update.callback_query.edit_message_caption.call_args.kwargs
        sum3_markup = sum3_call["reply_markup"]
        back_to_card2_btn = sum3_markup.inline_keyboard[0][0]
        self.assertEqual(back_to_card2_btn.callback_data, "inq:swipe:1")
        self.assertIn("返回老师卡片 (第 2/2 位) ➔", back_to_card2_btn.text)


if __name__ == "__main__":
    unittest.main()
