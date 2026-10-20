from __future__ import annotations

import sys
from datetime import datetime
from html import escape
from pathlib import Path
from time import time

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from core.i18n import DEFAULT_LANG, SUPPORTED_LANGUAGES, t
from core.service_registry import category_groups, registry

MAX_PER_CHANNEL = 5
RESULTS_PER_PAGE = 10
DIVIDER = "────────────────────────"


def _lang(update: object = None) -> str:
    return DEFAULT_LANG


if category_groups.groups:

    SERVICE_TYPES = [(code, f"group_{code.lower()}") for code in category_groups.groups]
else:
    SERVICE_TYPES = [(cat, f"type_{cat.lower()}") for cat in registry.categories]


def _relative_date(ts: int, lang: str = "zh") -> str:
    age = max(0, int(time()) - ts)
    if age < 60:
        return t("just_now", lang)
    if age < 3600:
        return t("minutes_ago", lang, n=max(1, age // 60))
    if age < 86400:
        return t("hours_ago", lang, n=max(1, age // 3600))
    days = age // 86400
    if days < 7:
        return t("days_ago", lang, n=max(1, days))
    weeks = days // 7
    if weeks < 4:
        return t("weeks_ago", lang, n=max(1, weeks))
    months = max(1, days // 30)
    return t("months_ago", lang, n=months)


def _service_label(service_value: str | None, lang: str = DEFAULT_LANG) -> str:
    effective_lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANG
    if not service_value:
        return t("browse_any", effective_lang)
    upper_val = service_value.upper()
    if upper_val in category_groups.groups:
        return category_groups.get_label(upper_val, effective_lang)
    lower_val = service_value.lower()
    for code, key in SERVICE_TYPES:
        if code.lower() == lower_val or code.upper() == upper_val:
            return t(key, effective_lang)
    lbl = registry.get_label(upper_val, effective_lang)
    if lbl and lbl != upper_val:
        return lbl
    lbl = registry.get_label(lower_val, effective_lang)
    if lbl and lbl != lower_val:
        return lbl
    return service_value


def _format_chinese_date(ts: int) -> str:
    dt = datetime.fromtimestamp(ts)
    return f"{dt.year}年{dt.month}月{dt.day}日 {dt.strftime('%H:%M')}"


def _freshness_badge(ts: int) -> str:
    age = max(0, int(time()) - ts)
    if age < 3600:
        return "🟢"
    if age < 3 * 86400:
        return "🟡"
    return "⚪"


def _format_price_badge(price_val: object) -> str:
    if price_val is None or price_val == "" or price_val == 0:
        return ""
    try:
        val = float(price_val)
        val_str = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
        return f"  💰 <b>￥{val_str}</b>"
    except (ValueError, TypeError):
        str_val = str(price_val).strip()
        if not str_val.startswith("￥") and not str_val.startswith("$"):
            str_val = f"￥{str_val}"
        return f"  💰 <b>{escape(str_val)}</b>"


def _format_result(r: dict, lang: str = "zh", view_mode: str = "card") -> str:
    # 1. Service keywords
    service_code = r.get("ext_service_category")
    if service_code:
        codes = [c.strip() for c in service_code.split(",") if c.strip()]
        labels = [_service_label(c, lang) for c in codes]
        service_str = "·".join(labels)
        if len(service_str) > 12:
            service_str = service_str[:11] + "…"
    else:
        service_str = "未标注"

    # 2. Location (City / District / Landmark)
    district = (r.get("ext_district") or "").strip()
    city = (r.get("ext_city") or "").strip()
    landmark = (r.get("ext_landmark") or "").strip()

    loc_parts = [p for p in [district or city, landmark] if p]
    if loc_parts:
        location_str = "·".join(loc_parts)
        if len(location_str) > 12:
            location_str = location_str[:11] + "…"
    else:
        location_str = "未标注"

    # 3. Price badge
    price_badge = _format_price_badge(r.get("ext_price"))

    # 4. Group / Channel Name
    chat_title = (r.get("chat_title") or "未知").strip()

    # 5. Relative date & freshness badge
    date_ts = r.get("date", int(time()))
    date_str = _relative_date(date_ts, lang)
    freshness = _freshness_badge(date_ts)

    # 6. Duplicate badge if any
    dup_count = r.get("dup_count", 0)
    dup_badge = f"  ℹ️ <i>+{dup_count}条重复</i>" if dup_count > 0 else ""

    # Line 1: service type, location, price, date
    line1 = f"🏷️ <b>{escape(service_str)}</b>  📍 <b>{escape(location_str)}</b>{price_badge}  {freshness} <b>{escape(date_str)}</b>"

    # Line 2: group name
    line2 = f"📢 <b>{escape(chat_title)}</b>{dup_badge}"

    card_header = f"{line1}\n{line2}"

    # Make the whole text clickable redirecting to message_link if available
    msg_link = r.get("message_link")
    if msg_link:
        header = f'<a href="{escape(msg_link)}">{card_header}</a>'
    else:
        header = card_header

    # Optional Line 3: Text snippet if view_mode is "card"
    snippet_part = ""
    if view_mode == "card":
        raw_text = (r.get("text") or "").strip()
        if raw_text:
            clean_text = " ".join(raw_text.split())
            if len(clean_text) > 100:
                clean_text = clean_text[:97] + "…"
            snippet_part = (
                f"\n💬 <b>消息原文:</b>\n"
                f"<blockquote><i>“{escape(clean_text)}”</i></blockquote>"
            )

    quote_tag = "blockquote expandable" if view_mode == "card" else "blockquote"
    closing_tag = "blockquote"

    return (
        f"<{quote_tag}>"
        f"{header}"
        f"{snippet_part}"
        f"</{closing_tag}>"
    )


async def send_news(bot: object, chat_id: int, lang: str = "zh") -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    text = t("news_feed_placeholder", lang)
    back_button = [[InlineKeyboardButton(t("btn_back", lang), callback_data="feat:start")]]
    markup = InlineKeyboardMarkup(back_button)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=markup,
    )


def _render_page(
    results: list[dict],
    label: str,
    page: int,
    chat_filter: int | None,
    lang: str = "zh",
    view_mode: str = "card",
    sort_mode: str = "score",
    total_count: int | None = None,
    buffer_offset: int = 0,
    sub_query: str | None = None,
) -> tuple[str, object | None]:
    from telegram import InlineKeyboardMarkup
    from ui.pagination import _make_control_row, _make_pagination_row

    total = total_count if total_count is not None else len(results)
    if not total:
        empty_query = f"{label} (二次筛选: {sub_query})" if sub_query else label
        return t("no_results", lang, query=empty_query), None

    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    page        = max(0, min(page, total_pages - 1))
    
    # Calculate slice relative to buffer
    global_start = page * RESULTS_PER_PAGE
    global_end   = min(global_start + RESULTS_PER_PAGE, total)
    local_start  = global_start - buffer_offset
    local_end    = local_start + RESULTS_PER_PAGE

    if local_start >= 0:
        page_slice = results[local_start:local_end]
    else:
        page_slice = results[:RESULTS_PER_PAGE]

    body = "\n\n".join(_format_result(r, lang, view_mode=view_mode) for r in page_slice)
    filter_hint = t("filter_hint", lang) if chat_filter else ""
    footer = t("footer", lang, start=global_start + 1, end=global_end, total=total, page=page + 1, total_pages=total_pages, filter_hint=filter_hint)

    header_label = f"{label} <i>[筛选: {escape(sub_query)}]</i>" if sub_query else label
    text = f"🔍 <b>{header_label}</b>\n\n{body}\n\n{DIVIDER}\n{footer}"
    if len(text) > 4096:
        text = text[:4090] + "…"

    rows = []
    page_row = _make_pagination_row("sp", page, total_pages, total_count=total)
    if page_row:
        rows.append(page_row)
    control_row = _make_control_row("sp", view_mode=view_mode, sort_mode=sort_mode, sub_query=sub_query)
    rows.append(control_row)

    markup = InlineKeyboardMarkup(rows)
    return text, markup


