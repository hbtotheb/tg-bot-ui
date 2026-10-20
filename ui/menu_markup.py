from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.i18n import t
from ui.formatters import SERVICE_TYPES, _service_label
from ui.locations import get_all_configured_cities, get_configured_districts

PRICE_BUCKETS = [
    (None,   100,    "price_lt100"),
    (100,    500,    "price_100_500"),
    (500,    1000,   "price_500_1k"),
    (1000,   5000,   "price_1k_5k"),
    (5000,   None,   "price_5k_plus"),
]


def _browse_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    state = context.user_data.setdefault(
        "browse",
        {
            "service": [],
            "city": None,
            "district": [],
            "price_idx": None,
            "page": 0,
            "cities": get_all_configured_cities(),
            "city_counts": {},
            "service_counts": {},
            "districts": [],
            "district_counts": {},
            "active_picker": None,
        },
    )
    if not state.get("cities"):
        state["cities"] = get_all_configured_cities()

    if isinstance(state.get("service"), str):
        state["service"] = [state["service"]] if state["service"] else []
    elif state.get("service") is None:
        state["service"] = []

    if isinstance(state.get("city"), list):
        state["city"] = state["city"][0] if state["city"] else None

    if isinstance(state.get("district"), str):
        state["district"] = [state["district"]] if state["district"] else []
    elif state.get("district") is None:
        state["district"] = []

    return state


def _price_label(idx: int | None, lang: str) -> str:
    if idx is None:
        return t("browse_any", lang)
    if 0 <= idx < len(PRICE_BUCKETS):
        _, _, key = PRICE_BUCKETS[idx]
        return t(key, lang)
    return t("browse_any", lang)


def _service_label_multi(services: list[str] | str | None, lang: str) -> str:
    if not services:
        return "⚪ 任意"
    if isinstance(services, str):
        services = [services]
    labels = [_service_label(code, lang) for code in services if code]
    if not labels:
        return "⚪ 任意"
    return "🟢 " + ", ".join(labels)


def _city_label(city: str | None, lang: str) -> str:
    return f"📍 {city}" if city else "⚪ 任意"


def _district_label_multi(districts: list[str] | str | None, lang: str) -> str:
    if not districts:
        return "⚪ 任意"
    if isinstance(districts, str):
        districts = [districts]
    districts = [d for d in districts if d]
    if not districts:
        return "⚪ 任意"
    if len(districts) == 1:
        return f"🎯 {districts[0]}"
    return f"🎯 {districts[0]} 等{len(districts)}处"


def _format_count_badge(cnt: int) -> str:
    if cnt <= 0:
        return ""
    if cnt >= 10000:
        return f" ({cnt // 10000}万+)"
    if cnt >= 1000:
        return f" ({cnt // 1000}千+)"
    if cnt >= 100:
        return f" ({cnt // 100}百+)"
    return f" ({cnt})"


def _browse_menu_markup(state: dict, lang: str = "zh", loading: bool = False) -> InlineKeyboardMarkup:
    active = state.get("active_picker")
    rows: list[list[InlineKeyboardButton]] = []

    # 0. Teacher Swipe Card Entry (Swipe card)
    rows.append([InlineKeyboardButton("💃 推荐老师 (滑动卡片)", callback_data="tc:swipe:0")])
    rows.append([InlineKeyboardButton("🤖 AI对话", callback_data="inq:start")])

    # 1. Service Filter Button & Multi-select Options
    selected_services = set(state.get("service") or [])
    srv_has_sel = len(selected_services) > 0
    srv_val = _service_label_multi(state["service"], lang)
    srv_ind = " 🔼" if active == "service" else " 🔽"
    srv_prefix = "🟢 " if srv_has_sel else ""
    rows.append([InlineKeyboardButton(f"{srv_prefix}🏷️ 服务分类: {srv_val}{srv_ind}", callback_data="br:sm")])

    if active == "service":
        service_counts = state.get("service_counts") or {}
        any_label = ("✅ " if not selected_services else "⚪ ") + "不限 / 全部"
        s_rows = [[InlineKeyboardButton(any_label, callback_data="br:ss:_any")]]
        service_row: list[InlineKeyboardButton] = []
        for code, key in SERVICE_TYPES:
            label = t(key, lang)
            cnt = service_counts.get(code, 0)
            cnt_str = _format_count_badge(cnt)
            if code in selected_services:
                label = f"✅ {label}{cnt_str}"
            else:
                label = f"{label}{cnt_str}"
            service_row.append(InlineKeyboardButton(label, callback_data=f"br:ss:{code}"))
        if service_row:
            s_rows.append(service_row)
        rows.extend(s_rows)

    # 2. City Filter Button & Single-select Options
    current_city = state.get("city")
    city_has_sel = current_city is not None
    city_val = _city_label(current_city, lang)
    city_ind = " 🔼" if active == "city" else " 🔽"
    city_prefix = "📍 " if city_has_sel else ""
    rows.append([InlineKeyboardButton(f"{city_prefix}🏙️ 目标城市: {city_val}{city_ind}", callback_data="br:cm")])

    if active == "city":
        cities = state.get("cities") or get_all_configured_cities()
        city_counts = state.get("city_counts") or {}
        any_label = ("✅ " if current_city is None else "⚪ ") + "不限 / 全城"
        c_rows = [[InlineKeyboardButton(any_label, callback_data="br:sc:_any")]]
        triplet: list[InlineKeyboardButton] = []
        for idx, city in enumerate(cities):
            city_name = city or "?"
            cnt = city_counts.get(city_name, 0)
            cnt_str = _format_count_badge(cnt)
            if current_city == city_name:
                label = f"✅ {city_name}{cnt_str}"
            else:
                label = f"{city_name}{cnt_str}"
            label = label[:24]
            triplet.append(InlineKeyboardButton(label, callback_data=f"br:sc:{idx}"))
            if len(triplet) == 3:
                c_rows.append(triplet)
                triplet = []
        if triplet:
            c_rows.append(triplet)
        rows.extend(c_rows)

    # 3. District Filter Button & Multi-select Options
    if current_city:
        selected_dists = set(state.get("district") or [])
        dist_has_sel = len(selected_dists) > 0
        dist_val = _district_label_multi(state["district"], lang)
        dist_ind = " 🔼" if active == "district" else " 🔽"
        dist_prefix = "🎯 " if dist_has_sel else ""
        rows.append([InlineKeyboardButton(f"{dist_prefix}📍 地标区域: {dist_val}{dist_ind}", callback_data="br:dm")])

        if active == "district":
            districts = state.get("districts") or get_configured_districts(current_city)
            dist_counts = state.get("district_counts") or {}
            any_label = ("✅ " if not selected_dists else "⚪ ") + "不限 / 全区"
            d_rows = [[InlineKeyboardButton(any_label, callback_data="br:sd:_any")]]
            pair: list[InlineKeyboardButton] = []
            for idx, dist in enumerate(districts):
                dist_name = dist or "?"
                cnt = dist_counts.get(dist_name, 0)
                cnt_str = _format_count_badge(cnt)
                if dist_name in selected_dists:
                    label = f"✅ {dist_name}{cnt_str}"
                else:
                    label = f"{dist_name}{cnt_str}"
                label = label[:24]
                pair.append(InlineKeyboardButton(label, callback_data=f"br:sd:{idx}"))
                if len(pair) == 2:
                    d_rows.append(pair)
                    pair = []
            if pair:
                d_rows.append(pair)
            rows.extend(d_rows)

    # 4. Sort Order Selector & Options
    sort_mode = state.get("sort_mode", "recent")
    sort_labels = {
        "recent": "🆕 最新发布",
        "score": "💎 热门权重",
        "price_asc": "💰 价格从低到高",
        "price_desc": "💰 价格从高到低",
    }
    curr_sort_label = sort_labels.get(sort_mode, "🆕 最新发布")
    sort_ind = " 🔼" if active == "sort" else " 🔽"
    rows.append([InlineKeyboardButton(f"📊 排序方式: {curr_sort_label}{sort_ind}", callback_data="br:srm")])

    if active == "sort":
        sort_opts = [
            ("recent", "🆕 最新发布"),
            ("score", "💎 热门权重"),
            ("price_asc", "💰 价格从低到高"),
            ("price_desc", "💰 价格从高到低"),
        ]
        s_rows = []
        for code, label in sort_opts:
            prefix = "✅ " if sort_mode == code else "⚪ "
            s_rows.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"br:so:{code}")])
        rows.extend(s_rows)

    # 5. Action Buttons
    go_label = "⏳ 正在查询结果..." if loading else "🚀 立即查询结果"
    rows.append([InlineKeyboardButton(go_label, callback_data="br:go:0")])
    rows.append([InlineKeyboardButton("🔄 重置所有筛选", callback_data="br:reset")])

    return InlineKeyboardMarkup(rows)




def _render_browse_menu(state: dict, lang: str, loading: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    text = t(
        "browse_title", lang,
        service=_service_label_multi(state["service"], lang),
        city=_city_label(state["city"], lang),
        district=_district_label_multi(state["district"], lang),
        price=_price_label(state["price_idx"], lang),
    )
    return text, _browse_menu_markup(state, lang, loading=loading)
