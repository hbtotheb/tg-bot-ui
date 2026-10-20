from __future__ import annotations

import sys
import unittest
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

try:
    from core.mock_db import MockDatabase
    from inquiry.search import search_and_rank_teachers
    from ui.teachers_card import format_teacher_card, format_teacher_reviews
    from ui.teachers_list import format_teachers_list
except ImportError:
    from bot.core.mock_db import MockDatabase
    from bot.inquiry.search import search_and_rank_teachers
    from bot.ui.teachers_card import format_teacher_card, format_teacher_reviews
    from bot.ui.teachers_list import format_teachers_list


class TestStandaloneMockDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = MockDatabase()
        await self.db.init()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_mock_teachers_and_ui_rendering(self) -> None:
        teachers = await self.db.search_teachers(city="上海")
        self.assertEqual(len(teachers), 4)

        top = teachers[0]
        self.assertEqual(top["name"], "小雅")

        # Verify card and list formatters work directly with MockDatabase records
        card_html, card_markup = format_teacher_card(top, index=0, total=len(teachers))
        self.assertIn("小雅", card_html)
        self.assertIsNotNone(card_markup)

        list_html, list_markup = format_teachers_list(
            teachers=teachers, page=0, total=len(teachers), page_size=8, query=None
        )
        self.assertIn("小雅", list_html)
        self.assertIsNotNone(list_markup)

        revs = await self.db.get_teacher_reviews(top["id"])
        self.assertEqual(len(revs), 2)
        rev_html, rev_markup = format_teacher_reviews(top, revs, 0, page=0)
        self.assertIn("Mock 测评频道", rev_html)
        self.assertIsNotNone(rev_markup)

    async def test_mock_inquiry_search_and_raw_sql_adapter(self) -> None:
        ranked = await search_and_rank_teachers(
            self.db,
            query_info={
                "city": "上海",
                "keywords_list": ["大胸", "嫩妹"],
                "weights": {"visual": 0.3, "body": 0.4, "service": 0.2, "price": 0.1},
                "weight_focus": "body",
                "price_max": 1600.0,
            },
            location_text="静安",
            limit=5,
        )
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["name"], "小雅")

        # Verify _read() async SQLite adapter works for homepage district/tag suggestions
        async with self.db._read() as conn:
            cur = await conn.execute("SELECT district, COUNT(*) as cnt FROM teachers GROUP BY district")
            rows = await cur.fetchall()
            self.assertGreaterEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
