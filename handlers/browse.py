from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.dedup import interleave_by_channel
from core.i18n import t
from core.service_registry import category_groups
from core.shared import db
from ui.formatters import DIVIDER, RESULTS_PER_PAGE, _format_result, _lang
from ui.locations import get_all_configured_cities, get_configured_districts
from ui.menu_markup import (
    PRICE_BUCKETS,
    _browse_menu_markup,
    _browse_state,
    _render_browse_menu,
)
from ui.pagination import _make_control_row, _make_pagination_row

_format_listing = _format_result

CHUNK_SIZE = int(os.getenv("SEARCH_CHUNK_SIZE", "100"))


def _render_browse_results(
    results: list[dict],
    state: dict,
    page: int,
    lang: str,
    total_count: int | None = None,
    buffer_offset: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    view_mode = state.get("view_mode", "card")
    sort_mode = state.get("sort_mode", "recent")
    sub_query = state.get("sub_query")

    total = total_count if total_count is not None else len(results)
    if not total:
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(t("btn_filters", lang), callback_data="br:menu")],
        ])
        no_res_query = f"(二次筛选: {sub_query})" if sub_query else ""
        return f"{t('browse_no_results', lang)} {no_res_query}".strip(), markup

    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    page        = max(0, min(page, total_pages - 1))

    global_start = page * RESULTS_PER_PAGE
    global_end   = min(global_start + RESULTS_PER_PAGE, total)
    local_start  = global_start - buffer_offset
    local_end    = local_start + RESULTS_PER_PAGE

    if local_start >= 0:
        page_slice = results[local_start:local_end]
    else:
        page_slice = results[:RESULTS_PER_PAGE]

    text = "\n\n".join(_format_listing(r, lang, view_mode=view_mode) for r in page_slice)
    subkw_hint = f" · 二次筛选: {sub_query}" if sub_query else ""
    text += (
        f"\n\n{DIVIDER}\n"
        + t("browse_footer", lang, total=total, page=page + 1, total_pages=total_pages) + subkw_hint
    )
    if len(text) > 4096:
        text = text[:4090] + "…"

    rows: list[list[InlineKeyboardButton]] = []
    page_row = _make_pagination_row("br:go", page, total_pages, total_count=total)
    if page_row:
        rows.append(page_row)
    control_row = _make_control_row("br", view_mode=view_mode, sort_mode=sort_mode, sub_query=sub_query)
    rows.append(control_row)
    rows.append([InlineKeyboardButton(t("btn_filters", lang), callback_data="br:menu")])
    return text, InlineKeyboardMarkup(rows)



async def cmd_browse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang  = _lang(update)
    state = _browse_state(context)
    state["cities"] = get_all_configured_cities()
    text, markup = _render_browse_menu(state, lang)
    if update.effective_message:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def _show_browse_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang  = _lang(update)
    state = _browse_state(context)
    if not state.get("cities"):
        state["cities"] = get_all_configured_cities()

    active = state.get("active_picker")
    if active == "service" and not state.get("service_counts"):
        raw_counts = await db.get_service_category_counts(state.get("city"))
        state["service_counts"] = category_groups.aggregate_counts(raw_counts)
    elif active == "city" and not state.get("city_counts"):
        state["city_counts"] = await db.get_city_counts()
    elif active == "district" and state.get("city") and not state.get("district_counts"):
        state["district_counts"] = await db.get_location_counts(state["city"])

    text, markup = _render_browse_menu(state, lang)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def show_browse_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_browse_menu(update, context)


async def _show_browse_results(
    update: Update, context: ContextTypes.DEFAULT_TYPE, page: int,
) -> None:
    lang  = _lang(update)
    state = _browse_state(context)

    price_idx = state["price_idx"]
    price_min, price_max = (None, None)
    if price_idx is not None and 0 <= price_idx < len(PRICE_BUCKETS):
        price_min, price_max, _ = PRICE_BUCKETS[price_idx]

    selected_services = state["service"] if state["service"] else None
    resolved_services = category_groups.resolve_sub_categories(selected_services) if selected_services else None
    sort_mode = state.get("sort_mode", "recent")
    sub_query = state.get("sub_query")

    cache_key = f"{resolved_services}:{state.get('city')}:{state.get('district')}:{price_min}:{price_max}:{sort_mode}:{sub_query}"
    pages_per_chunk = max(1, CHUNK_SIZE // RESULTS_PER_PAGE)
    target_offset = (page // pages_per_chunk) * CHUNK_SIZE

    same_browse_cache = (
        state.get("browse_cache_key") == cache_key
        and "browse_results" in state
    )
    if (
        same_browse_cache
        and state.get("browse_buffer_offset") == target_offset
    ):
        results = state["browse_results"]
        total_count = state.get("browse_total_count", len(results))
    else:
        if same_browse_cache and "browse_total_count" in state:
            total_count = state["browse_total_count"]
        else:
            total_count = await db.count_extracted(
                service_category=resolved_services,
                city=state["city"],
                district=state["district"] if state["district"] else None,
                price_min=price_min,
                price_max=price_max,
                sub_query=sub_query,
            )
        results = await db.search_extracted(
            service_category=resolved_services,
            city=state["city"],
            district=state["district"] if state["district"] else None,
            price_min=price_min,
            price_max=price_max,
            limit=CHUNK_SIZE,
            offset=target_offset,
            sort_by=sort_mode,
            sub_query=sub_query,
        )
        results = interleave_by_channel(results)
        state["browse_cache_key"] = cache_key
        state["browse_results"] = results
        state["browse_buffer_offset"] = target_offset
        state["browse_total_count"] = total_count

        user_id = update.effective_user.id if update.effective_user else None
        await db.record_telemetry(
            event="browse_results",
            user_id=user_id,
            result_count=total_count,
            details={
                "city": state.get("city"),
                "services": state.get("service"),
                "districts": state.get("district"),
                "price_idx": state.get("price_idx"),
                "sub_query": sub_query,
                "sort_mode": sort_mode,
            },
        )


    state["page"] = page
    text, markup = _render_browse_results(results, state, page, lang, total_count=total_count, buffer_offset=target_offset)
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True,
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True,
        )


from core.rate_limiter import rate_limiter


async def on_browse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.callback_query.data:
        return
    user = update.effective_user
    if user and rate_limiter.is_callback_rate_limited(user.id, user.username):
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        return

    lang  = _lang(update)
    state = _browse_state(context)
    data  = update.callback_query.data
    if "noop" in data:
        await update.callback_query.answer()
        return

    try:
        await _handle_browse_callback_action(update, context, state, data)
    finally:
        try:
            await update.callback_query.answer()
        except Exception:
            pass


async def _handle_browse_callback_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict, data: str
) -> None:
    parts = data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""

    if action == "tvm":
        curr_vm = state.get("view_mode", "card")
        state["view_mode"] = "compact" if curr_vm == "card" else "card"
        await _show_browse_results(update, context, state.get("page", 0))
        return

    if action == "tsort":
        curr_sort = state.get("sort_mode", "recent")
        state["sort_mode"] = "score" if curr_sort == "recent" else "recent"
        await _show_browse_results(update, context, state.get("page", 0))
        return

    if action == "menu":
        state["active_picker"] = None
        await _show_browse_menu(update, context)
        return

    if action == "reset":
        state["service"] = []
        state["city"] = None
        state["district"] = []
        state["price_idx"] = None
        state["page"] = 0
        state["active_picker"] = None
        await _show_browse_menu(update, context)
        return

    if action == "srm":
        state["active_picker"] = None if state.get("active_picker") == "sort" else "sort"
        await _show_browse_menu(update, context)
        return

    if action == "subkw":
        context.user_data["awaiting_subkw"] = "browse"
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(
                "🔎 <b>请输入需要在当前结果中筛选的二次关键词：</b>\n<i>直接发送文字即可，例如：输入 \"静安\" 或 \"包夜\"。</i>",
                parse_mode="HTML"
            )
        if update.callback_query:
            await update.callback_query.answer()
        return

    if action == "clearsubkw":
        state.pop("sub_query", None)
        state["page"] = 0
        await _show_browse_results(update, context, 0)
        return

    if action == "so":

        value = parts[2] if len(parts) > 2 else "recent"
        state["sort_mode"] = value
        state["active_picker"] = None
        await _show_browse_menu(update, context)
        return

    if action == "sm":

        if state.get("active_picker") == "service":
            state["active_picker"] = None
        else:
            raw_counts = await db.get_service_category_counts(state.get("city"))
            state["service_counts"] = category_groups.aggregate_counts(raw_counts)
            state["active_picker"] = "service"
        await _show_browse_menu(update, context)
        return

    if action == "pm":
        state["active_picker"] = None if state.get("active_picker") == "price" else "price"
        await _show_browse_menu(update, context)
        return

    if action == "cm":
        if state.get("active_picker") == "city":
            state["active_picker"] = None
        else:
            configured_cities = get_all_configured_cities()
            city_counts = await db.get_city_counts()
            db_cities = list(city_counts.keys())
            state["cities"] = list(dict.fromkeys(configured_cities + db_cities))
            state["city_counts"] = city_counts
            state["active_picker"] = "city"
        await _show_browse_menu(update, context)
        return

    if action == "dm":
        if not state["city"]: return
        if state.get("active_picker") == "district":
            state["active_picker"] = None
        else:
            configured_dists = get_configured_districts(state["city"])
            db_dists = await db.get_districts(state["city"])
            db_landmarks = await db.get_landmarks(state["city"])
            dist_counts = await db.get_location_counts(state["city"])
            state["districts"] = list(dict.fromkeys(configured_dists + db_dists + db_landmarks))
            state["district_counts"] = dist_counts
            state["active_picker"] = "district"
        await _show_browse_menu(update, context)
        return

    if action == "ss":
        value = parts[2] if len(parts) > 2 else "_any"
        if value == "_any":
            state["service"] = []
        else:
            curr = list(state.get("service") or [])
            if value in curr:
                curr.remove(value)
            else:
                curr.append(value)
            state["service"] = curr
        state["active_picker"] = "service"
        await _show_browse_menu(update, context)
        return

    if action == "sp":
        value = parts[2] if len(parts) > 2 else "_any"
        if value == "_any":
            state["price_idx"] = None
        else:
            try:
                idx = int(value)
                if 0 <= idx < len(PRICE_BUCKETS):
                     state["price_idx"] = idx
            except ValueError:
                pass
        state["active_picker"] = None
        await _show_browse_menu(update, context)
        return

    if action == "sc":
        value = parts[2] if len(parts) > 2 else "_any"
        if value == "_any":
            state["city"] = None
            state["district"] = []
            state["districts"] = []
            state["district_counts"] = {}
        else:
            try:
                idx = int(value)
                cities = state.get("cities") or get_all_configured_cities()
                if 0 <= idx < len(cities):
                    target = cities[idx]
                    state["city"] = target
                    state["district"] = []
                    configured_dists = get_configured_districts(target)
                    db_dists = await db.get_districts(target)
                    db_landmarks = await db.get_landmarks(target)
                    dist_counts = await db.get_location_counts(target)
                    state["districts"] = list(dict.fromkeys(configured_dists + db_dists + db_landmarks))
                    state["district_counts"] = dist_counts
            except ValueError:
                pass
        state["active_picker"] = None
        await _show_browse_menu(update, context)
        return

    if action == "sd":
        value = parts[2] if len(parts) > 2 else "_any"
        if value == "_any":
            state["district"] = []
        else:
            try:
                idx = int(value)
                districts = state.get("districts") or get_configured_districts(state.get("city"))
                if 0 <= idx < len(districts):
                    target = districts[idx]
                    curr = list(state.get("district") or [])
                    if target in curr:
                        curr.remove(target)
                    else:
                        curr.append(target)
                    state["district"] = curr
            except ValueError:
                pass
        state["active_picker"] = "district"
        await _show_browse_menu(update, context)
        return

    if action == "go":
        state["active_picker"] = None
        try:
            page = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            page = 0

        # Temporarily update button text to show loading indicator feedback
        if update.callback_query and update.callback_query.message:
            try:
                loading_markup = _browse_menu_markup(state, lang, loading=True)
                await update.callback_query.edit_message_reply_markup(reply_markup=loading_markup)
            except Exception:
                pass

        await _show_browse_results(update, context, page)
        return
