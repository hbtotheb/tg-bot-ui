from __future__ import annotations

import copy
import json
import logging
import sqlite3
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "mock_data.json"


class _AsyncCursorAdapter:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    async def fetchall(self) -> list[sqlite3.Row]:
        return self._cursor.fetchall()

    async def fetchone(self) -> sqlite3.Row | None:
        return self._cursor.fetchone()


class _AsyncConnAdapter:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: Any = ()) -> _AsyncCursorAdapter:
        cur = self._conn.execute(sql, params)
        return _AsyncCursorAdapter(cur)


class MockDatabase:
    """In-memory mock database for standalone Bot UI development and testing without backend/DB."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self.path = ":memory: (mock_data.json)"
        self._fixture_path = Path(fixture_path) if fixture_path else FIXTURES_PATH
        self._teachers: list[dict[str, Any]] = []
        self._reviews: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = []
        self._users: dict[int, dict[str, Any]] = {}
        self._telemetry: list[dict[str, Any]] = []
        self._mem_conn: sqlite3.Connection | None = None
        self._load_fixtures()

    def _load_fixtures(self) -> None:
        data: dict[str, Any] = {}
        if self._fixture_path.exists():
            try:
                with open(self._fixture_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning("Failed to load mock_data.json: %s", e)

        self._teachers = data.get("teachers", [])
        self._reviews = data.get("reviews", [])
        self._messages = data.get("messages", [])

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE teachers (id INTEGER PRIMARY KEY, name TEXT, city TEXT, district TEXT, tags TEXT, status TEXT)"
        )
        for t in self._teachers:
            conn.execute(
                "INSERT INTO teachers (id, name, city, district, tags, status) VALUES (?, ?, ?, ?, ?, ?)",
                (t.get("id"), t.get("name"), t.get("city"), t.get("district"), t.get("tags"), t.get("status", "active")),
            )
        conn.commit()
        self._mem_conn = conn

    async def init(self) -> None:
        logger.info("Initialized standalone MockDatabase with %d teachers, %d reviews, %d messages", len(self._teachers), len(self._reviews), len(self._messages))

    async def close(self) -> None:
        if self._mem_conn:
            self._mem_conn.close()
            self._mem_conn = None

    @asynccontextmanager
    async def _read(self):
        if self._mem_conn is None:
            self._load_fixtures()
        yield _AsyncConnAdapter(self._mem_conn)

    async def execute_write(self, sql: str, params: Any = ()) -> None:
        return None

    async def register_user(self, chat_id: int, username: str | None = None, first_name: str | None = None, last_name: str | None = None, language: str | None = None) -> None:
        self._users[chat_id] = {
            "chat_id": chat_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "language": language,
        }

    async def get_bot_users(self) -> list[dict[str, Any]]:
        return list(self._users.values())

    async def record_telemetry(self, event: str, user_id: int | None = None, query: str | None = None, result_count: int | None = None, details: dict | None = None) -> None:
        self._telemetry.append({"event": event, "user_id": user_id, "query": query, "result_count": result_count, "details": details})

    def _filter_teachers(
        self,
        query: str | None = None,
        city: Any = None,
        district: Any = None,
        price_min: float | None = None,
        price_max: float | None = None,
        rating_min: float | None = None,
        status: str | None = "active",
        include_inactive: bool = False,
        match_any: bool = False,
    ) -> list[dict[str, Any]]:
        results = []
        cities = {city} if isinstance(city, str) else set(city or [])
        dists = {district} if isinstance(district, str) else set(district or [])
        terms = [t.strip() for t in (query or "").split() if t.strip()]

        for t in self._teachers:
            if not include_inactive and status and status != "all":
                if (t.get("status") or "active") != status:
                    continue
            if cities and t.get("city") not in cities and t.get("canonical_city") not in cities:
                continue
            if dists and t.get("district") not in dists and t.get("landmark") not in dists:
                continue
            p = t.get("price")
            if price_min is not None and (p is None or p < price_min):
                continue
            if price_max is not None and (p is None or p > price_max):
                continue
            r = t.get("rating")
            if rating_min is not None and (r is None or r < rating_min):
                continue
            if terms:
                haystack = " ".join(
                    str(t.get(k) or "")
                    for k in ("name", "canonical_name", "city", "district", "landmark", "tags", "summary")
                ).lower()
                if match_any:
                    if not any(term.lower() in haystack for term in terms):
                        continue
                else:
                    if not all(term.lower() in haystack for term in terms):
                        continue
            results.append(copy.deepcopy(t))
        return results

    async def search_teachers(
        self,
        query: str | None = None,
        *,
        city: Any = None,
        district: Any = None,
        price_min: float | None = None,
        price_max: float | None = None,
        rating_min: float | None = None,
        status: str | None = "active",
        include_inactive: bool = False,
        match_any: bool = False,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "rank",
    ) -> list[dict[str, Any]]:
        items = self._filter_teachers(query, city, district, price_min, price_max, rating_min, status, include_inactive, match_any)
        if sort_by == "rating":
            items.sort(key=lambda x: (x.get("rating") or 0.0, x.get("quality_mass") or 0.0), reverse=True)
        elif sort_by == "recent":
            items.sort(key=lambda x: x.get("extracted_at") or 0, reverse=True)
        elif sort_by == "price_asc":
            items.sort(key=lambda x: x.get("price") if x.get("price") is not None else 999999.0)
        elif sort_by == "price_desc":
            items.sort(key=lambda x: x.get("price") or 0.0, reverse=True)
        else:
            items.sort(key=lambda x: (x.get("rank_score") or 0.0, x.get("quality_mass") or 0.0), reverse=True)
        return items[offset : offset + limit]

    async def count_teachers(
        self,
        query: str | None = None,
        *,
        city: Any = None,
        district: Any = None,
        price_min: float | None = None,
        price_max: float | None = None,
        rating_min: float | None = None,
        status: str | None = "active",
        include_inactive: bool = False,
        match_any: bool = False,
    ) -> int:
        return len(self._filter_teachers(query, city, district, price_min, price_max, rating_min, status, include_inactive, match_any))

    async def get_teacher(self, teacher_id: int) -> dict[str, Any] | None:
        for t in self._teachers:
            if t.get("id") == teacher_id:
                return copy.deepcopy(t)
        return None

    async def get_teacher_reviews(self, teacher_id: int, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        revs = [copy.deepcopy(r) for r in self._reviews if r.get("teacher_id") == teacher_id]
        revs.sort(key=lambda r: r.get("date") or 0, reverse=True)
        return revs[offset : offset + limit]

    async def get_review(self, review_id: int) -> dict[str, Any] | None:
        for r in self._reviews:
            if r.get("id") == review_id:
                return copy.deepcopy(r)
        return None

    async def update_teacher_photo(self, teacher_id: int, photo_path: str) -> None:
        for t in self._teachers:
            if t.get("id") == teacher_id:
                t["photo_path"] = photo_path

    def _filter_messages(self, query: str | None = None, chat_id: int | None = None) -> list[dict[str, Any]]:
        terms = [t.strip().lower() for t in (query or "").split() if t.strip()]
        out = []
        for m in self._messages:
            if chat_id and m.get("chat_id") != chat_id:
                continue
            text = str(m.get("text") or "").lower()
            if terms and not all(t in text for t in terms):
                continue
            out.append(copy.deepcopy(m))
        return out

    async def search(self, query: str, limit: int = 50, offset: int = 0, chat_id: int | None = None, sort_by: str = "score") -> list[dict[str, Any]]:
        items = self._filter_messages(query, chat_id)
        if sort_by == "recent":
            items.sort(key=lambda m: m.get("date") or 0, reverse=True)
        else:
            items.sort(key=lambda m: m.get("score") or 0.0, reverse=True)
        return items[offset : offset + limit]

    async def count_search(self, query: str, chat_id: int | None = None) -> int:
        return len(self._filter_messages(query, chat_id))

    async def recent(self, limit: int = 50, offset: int = 0, chat_id: int | None = None, sort_by: str = "recent") -> list[dict[str, Any]]:
        items = self._filter_messages(None, chat_id)
        if sort_by == "score":
            items.sort(key=lambda m: m.get("score") or 0.0, reverse=True)
        else:
            items.sort(key=lambda m: m.get("date") or 0, reverse=True)
        return items[offset : offset + limit]

    async def count_recent(self, chat_id: int | None = None) -> int:
        return len(self._filter_messages(None, chat_id))

    async def count(self) -> dict[str, int]:
        return {
            "messages": len(self._messages),
            "chats": len({m.get("chat_id") for m in self._messages}),
            "teachers": len(self._teachers),
            "reviews": len(self._reviews),
        }

    async def get_chats(self, limit: int = 20) -> list[dict[str, Any]]:
        chats: dict[int, dict[str, Any]] = {}
        for m in self._messages:
            cid = m["chat_id"]
            if cid not in chats:
                chats[cid] = {"chat_id": cid, "chat_title": m.get("chat_title"), "msg_count": 0, "last_date": 0}
            chats[cid]["msg_count"] += 1
            chats[cid]["last_date"] = max(chats[cid]["last_date"], m.get("date") or 0)
        return list(chats.values())[:limit]

    async def get_city_counts(self, limit: int = 20) -> list[dict[str, Any]]:
        c = Counter(m.get("ext_city") for m in self._messages if m.get("ext_city"))
        return [{"city": k, "count": v} for k, v in c.most_common(limit)]

    async def get_districts(self, city: str, limit: int = 20) -> list[dict[str, Any]]:
        c = Counter(m.get("ext_district") for m in self._messages if m.get("ext_city") == city and m.get("ext_district"))
        return [{"district": k, "count": v} for k, v in c.most_common(limit)]

    async def get_landmarks(self, city: str, district: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        c = Counter(
            m.get("ext_landmark")
            for m in self._messages
            if m.get("ext_city") == city and (not district or m.get("ext_district") == district) and m.get("ext_landmark")
        )
        return [{"landmark": k, "count": v} for k, v in c.most_common(limit)]

    async def get_service_category_counts(self, city: str | None = None, district: str | None = None) -> list[dict[str, Any]]:
        c = Counter(
            m.get("ext_service_category")
            for m in self._messages
            if (not city or m.get("ext_city") == city)
            and (not district or m.get("ext_district") == district)
            and m.get("ext_service_category")
        )
        return [{"service_category": k, "count": v} for k, v in c.most_common()]

    async def get_location_counts(self, limit: int = 15) -> list[dict[str, Any]]:
        c = Counter(f"{m.get('ext_city')} {m.get('ext_district')}" for m in self._messages if m.get("ext_city"))
        return [{"location": k, "count": v} for k, v in c.most_common(limit)]

    async def search_extracted(
        self,
        *,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        service_category: Any = None,
        sub_query: str | None = None,
        sort_by: str = "recent",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        items = self._filter_messages(sub_query)
        out = []
        for m in items:
            if city and m.get("ext_city") != city:
                continue
            if district and m.get("ext_district") != district:
                continue
            if landmark and m.get("ext_landmark") != landmark:
                continue
            p = m.get("ext_price")
            if price_min is not None and (p is None or p < price_min):
                continue
            if price_max is not None and (p is None or p > price_max):
                continue
            out.append(m)
        return out[offset : offset + limit]

    async def count_extracted(
        self,
        *,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        service_category: Any = None,
        sub_query: str | None = None,
    ) -> int:
        res = await self.search_extracted(
            city=city,
            district=district,
            landmark=landmark,
            price_min=price_min,
            price_max=price_max,
            service_category=service_category,
            sub_query=sub_query,
            limit=10000,
        )
        return len(res)

    async def get_daily_summary(self, days: int = 7) -> dict[str, Any]:
        return {"total_searches": len(self._telemetry), "unique_users": len(self._users) or 3, "zero_result_searches": 0}

    async def get_daily_active_users(self, days: int = 7) -> list[dict[str, Any]]:
        return [{"day": "2026-10-20", "dau": max(1, len(self._users))}]

    async def get_retention_overview(self) -> dict[str, Any]:
        return {"total_users": max(1, len(self._users)), "returning_users": 1, "retention_rate": 100.0}

    async def get_top_search_terms(self, days: int = 7, limit: int = 10) -> list[dict[str, Any]]:
        return [{"query": "静安", "count": 5}, {"query": "嫩妹", "count": 3}]

    async def get_zero_result_searches(self, days: int = 7, limit: int = 10) -> list[dict[str, Any]]:
        return []
