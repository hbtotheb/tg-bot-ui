from __future__ import annotations

import logging
from typing import Any

try:
    from tg_rec_engine import haversine_distance_km, score_teacher_candidate
except ImportError:
    import math

    def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def score_teacher_candidate(
        t: dict[str, Any],
        keywords: list[str],
        weights: dict[str, float],
        user_lat: float | None = None,
        user_lon: float | None = None,
        location_text: str | None = None,
        negative_keywords: list[str] | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
    ) -> float:
        return float(t.get("rank_score") or t.get("rating") or 4.0)

logger = logging.getLogger(__name__)

__all__ = [
    "haversine_distance_km",
    "score_teacher_candidate",
    "search_and_rank_teachers",
]


async def search_and_rank_teachers(
    db: Any,
    query_info: dict[str, Any],
    user_lat: float | None = None,
    user_lon: float | None = None,
    location_text: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Query candidate teachers from the database and sort them based on the LLM-derived
    query parameters, dynamic rubric weights, and keyword matches.
    """
    keywords = query_info.get("keywords_list") or []
    weights = query_info.get("weights") or {}
    city = query_info.get("city")
    weight_focus = query_info.get("weight_focus") or "service"
    loc_text = location_text or query_info.get("location_text")
    price_min = query_info.get("price_min")
    price_max = query_info.get("price_max")

    # Map weight focus to database sort_by parameter for initial candidate retrieval
    db_sort = "rating"
    if weight_focus == "price":
        db_sort = "price_asc"
    elif weight_focus in ("visual", "body", "service"):
        db_sort = "rating"

    # 1. Primary candidate fetch with keywords if available
    query_str = " ".join(keywords) if keywords else None
    matching_candidates: list[dict[str, Any]] = []
    backfill_candidates: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    clean_dist = loc_text.rstrip("区").rstrip("新区").strip() if loc_text else None

    if query_str:
        # If district is provided, fetch candidates in that district first
        if clean_dist:
            dist_kw_candidates = await db.search_teachers(
                query=query_str,
                city=city,
                district=clean_dist,
                price_min=price_min,
                price_max=price_max,
                match_any=True,
                sort_by=db_sort,
                limit=50,
                offset=0,
            )
            for t in dist_kw_candidates:
                if t["id"] not in seen_ids:
                    matching_candidates.append(t)
                    seen_ids.add(t["id"])

        # Also fetch candidates matching query across the whole city
        kw_candidates = await db.search_teachers(
            query=query_str,
            city=city,
            price_min=price_min,
            price_max=price_max,
            match_any=True,
            sort_by=db_sort,
            limit=50,
            offset=0,
        )
        for t in kw_candidates:
            if t["id"] not in seen_ids:
                matching_candidates.append(t)
                seen_ids.add(t["id"])

    # 2. Supplement candidate pool up to 50 with top profiles from the same district or city
    if len(matching_candidates) < 50:
        if clean_dist:
            dist_candidates = await db.search_teachers(
                city=city,
                district=clean_dist,
                price_min=price_min,
                price_max=price_max,
                sort_by=db_sort,
                limit=50,
                offset=0,
            )
            for t in dist_candidates:
                if t["id"] not in seen_ids:
                    backfill_candidates.append(t)
                    seen_ids.add(t["id"])

        if len(matching_candidates) + len(backfill_candidates) < 50:
            city_candidates = await db.search_teachers(
                query=loc_text if not city and loc_text else None,
                city=city,
                price_min=price_min,
                price_max=price_max,
                sort_by=db_sort,
                limit=50,
                offset=0,
            )
            for t in city_candidates:
                if t["id"] not in seen_ids:
                    backfill_candidates.append(t)
                    seen_ids.add(t["id"])

    # 3. If still under required limit, supplement overall top profiles
    if len(matching_candidates) + len(backfill_candidates) < limit:
        overall_candidates = await db.search_teachers(
            query=None,
            price_min=price_min,
            price_max=price_max,
            sort_by=db_sort,
            limit=50,
            offset=0,
        )
        for t in overall_candidates:
            if t["id"] not in seen_ids:
                backfill_candidates.append(t)
                seen_ids.add(t["id"])

    # If still under limit (e.g. strict price filter), fall back to broader backfill
    if len(matching_candidates) + len(backfill_candidates) < limit and (price_min is not None or price_max is not None):
        fallback_candidates = await db.search_teachers(
            query=None,
            city=city,
            sort_by=db_sort,
            limit=50,
            offset=0,
        )
        for t in fallback_candidates:
            if t["id"] not in seen_ids:
                backfill_candidates.append(t)
                seen_ids.add(t["id"])

    if not matching_candidates and not backfill_candidates:
        return []

    # 4. Score and sort matching candidates (always placed at the front)
    scored_matching = []
    for t in matching_candidates:
        score = score_teacher_candidate(
            t, keywords, weights, user_lat, user_lon, location_text=loc_text, price_min=price_min, price_max=price_max
        )
        t_copy = dict(t)
        t_copy["_match_score"] = score
        scored_matching.append(t_copy)
    scored_matching.sort(key=lambda x: x["_match_score"], reverse=True)

    # 5. Score and sort backfill candidates by highest score
    scored_backfill = []
    for t in backfill_candidates:
        score = score_teacher_candidate(
            t, keywords, weights, user_lat, user_lon, location_text=loc_text, price_min=price_min, price_max=price_max
        )
        t_copy = dict(t)
        t_copy["_match_score"] = score
        scored_backfill.append(t_copy)
    scored_backfill.sort(key=lambda x: x["_match_score"], reverse=True)

    # Matching candidates first, rest filled with highest scoring profiles up to limit
    combined = scored_matching + scored_backfill
    return combined[:limit]
