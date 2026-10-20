from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.dedup import interleave_by_channel
from core.i18n import t
from core.shared import db
from handlers.browse import cmd_browse
from handlers.features import send_homepage
from ui.formatters import MAX_PER_CHANNEL, RESULTS_PER_PAGE, _lang, _render_page

CHUNK_SIZE = int(os.getenv("SEARCH_CHUNK_SIZE", "100"))


async def _send_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
    page: int,
    edit: bool = False,
) -> None:
    lang        = _lang(update)
    chat_filter = context.user_data.get("chat_filter")
    view_mode   = context.user_data.get("view_mode", "card")
    sort_mode   = context.user_data.get("sort_mode", "score")
    sub_query   = context.user_data.get("sub_query")
    context.user_data["page"] = page

    effective_query = f"{query} {sub_query}" if sub_query else query
    cache_key = f"{effective_query}:{chat_filter}:{sort_mode}"
    pages_per_chunk = max(1, CHUNK_SIZE // RESULTS_PER_PAGE)
    target_offset = (page // pages_per_chunk) * CHUNK_SIZE

    same_query_cache = (
        context.user_data.get("search_cache_key") == cache_key
        and "search_results" in context.user_data
    )
    if (
        same_query_cache
        and context.user_data.get("search_buffer_offset") == target_offset
    ):
        results = context.user_data["search_results"]
        total_count = context.user_data.get("search_total_count", len(results))
    else:
        if same_query_cache and "search_total_count" in context.user_data:
            total_count = context.user_data["search_total_count"]
        else:
            total_count = await db.count_search(effective_query, chat_id=chat_filter)

        results = await db.search(
            effective_query, limit=CHUNK_SIZE, offset=target_offset, chat_id=chat_filter, sort_by=sort_mode
        )
        if not chat_filter:
            results = interleave_by_channel(results)
        context.user_data["search_cache_key"] = cache_key
        context.user_data["search_results"] = results
        context.user_data["search_buffer_offset"] = target_offset
        context.user_data["search_total_count"] = total_count

        user_id = update.effective_user.id if update.effective_user else None
        await db.record_telemetry(
            event="search",
            user_id=user_id,
            query=effective_query,
            result_count=total_count,
            details={"chat_filter": chat_filter, "sort_mode": sort_mode},
        )

    text, markup = _render_page(
        results,
        query,
        page,
        chat_filter,
        lang,
        view_mode=view_mode,
        sort_mode=sort_mode,
        total_count=total_count,
        buffer_offset=target_offset,
        sub_query=sub_query,
    )


    menu_btn = InlineKeyboardButton(t("btn_menu", lang), callback_data="feat:start")
    if markup:
        new_keyboard = list(markup.inline_keyboard) + [[menu_btn]]
        markup = InlineKeyboardMarkup(new_keyboard)
    else:
        markup = InlineKeyboardMarkup([[menu_btn]])

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )


async def _send_recent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
    edit: bool = False,
) -> None:
    lang        = _lang(update)
    chat_filter = context.user_data.get("chat_filter")
    view_mode   = context.user_data.get("view_mode", "card")
    sort_mode   = context.user_data.get("sort_mode", "recent")
    context.user_data["page"] = page

    cache_key = f"recent:{chat_filter}:{sort_mode}"
    pages_per_chunk = max(1, CHUNK_SIZE // RESULTS_PER_PAGE)
    target_offset = (page // pages_per_chunk) * CHUNK_SIZE

    same_recent_cache = (
        context.user_data.get("recent_cache_key") == cache_key
        and "recent_results" in context.user_data
    )
    if (
        same_recent_cache
        and context.user_data.get("recent_buffer_offset") == target_offset
    ):
        results = context.user_data["recent_results"]
        total_count = context.user_data.get("recent_total_count", len(results))
    else:
        if same_recent_cache and "recent_total_count" in context.user_data:
            total_count = context.user_data["recent_total_count"]
        else:
            total_count = await db.count_recent(chat_id=chat_filter)

        results = await db.recent(
            limit=CHUNK_SIZE, offset=target_offset, chat_id=chat_filter, sort_by=sort_mode
        )
        context.user_data["recent_cache_key"] = cache_key
        context.user_data["recent_results"] = results
        context.user_data["recent_buffer_offset"] = target_offset
        context.user_data["recent_total_count"] = total_count

    text, markup = _render_page(
        results,
        t("recent_label", lang),
        page,
        chat_filter,
        lang,
        view_mode=view_mode,
        sort_mode=sort_mode,
        total_count=total_count,
        buffer_offset=target_offset,
    )

    menu_btn = InlineKeyboardButton(t("btn_menu", lang), callback_data="feat:start")
    if markup:
        new_keyboard = list(markup.inline_keyboard) + [[menu_btn]]
        markup = InlineKeyboardMarkup(new_keyboard)
    else:
        markup = InlineKeyboardMarkup([[menu_btn]])

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        await db.register_user(
            chat_id=update.effective_chat.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language=user.language_code,
        )

    # Check deep link arguments (e.g. /start rdtl_{tid}_{rid}_{from_index}_{page}_{review_num})
    if context.args and context.args[0].startswith("rdtl_"):
        parts = context.args[0].split("_")
        try:
            tid = int(parts[1])
            rid = int(parts[2])
            from_idx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            rev_num = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
            try:
                from bot.handlers.teachers import show_review_detail
            except ImportError:
                from handlers.teachers import show_review_detail
            await show_review_detail(update, context, tid, rid, from_idx, page, rev_num)
            return
        except Exception:
            pass

    # Check inquiry review deep link arguments (e.g. /start irdtl_{tid}_{rid}_{from_index}_{page}_{review_num})
    if context.args and context.args[0].startswith("irdtl_"):
        parts = context.args[0].split("_")
        try:
            tid = int(parts[1])
            rid = int(parts[2])
            from_idx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            rev_num = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
            try:
                from bot.handlers.teachers import show_review_detail
            except ImportError:
                from handlers.teachers import show_review_detail
            await show_review_detail(
                update,
                context,
                tid,
                rid,
                from_idx,
                page,
                rev_num,
                back_callback=f"inq:swipe:{from_idx}",
                review_list_callback=f"inq:rev:{tid}:{from_idx}:{page}",
            )
            return
        except Exception:
            pass

    # Check teacher card deep link arguments (e.g. /start tc_{tid}_{from_page})
    if context.args and context.args[0].startswith("tc_"):
        parts = context.args[0].split("_")
        try:
            tid = int(parts[1])
            from_page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            try:
                from bot.handlers.teachers import show_teacher_card_by_id
            except ImportError:
                from handlers.teachers import show_teacher_card_by_id
            await show_teacher_card_by_id(update, context, tid, from_page)
            return
        except Exception:
            pass

    # Check inquiry deep link arguments (e.g. /start inq_look, inq_body, inq_val, inq_map, inq_confirm)
    if context.args and context.args[0].startswith("inq_"):
        try:
            from bot.inquiry.handlers import handle_inquiry_deeplink
        except ImportError:
            from inquiry.handlers import handle_inquiry_deeplink
        await handle_inquiry_deeplink(update, context, context.args[0])
        return

    # Check keyword search deep link arguments (e.g. /start kw_b64_{encoded} or /start kw_{keyword})
    if context.args and (context.args[0].startswith("kw_") or context.args[0].startswith("search_")):
        prefix_len = 3 if context.args[0].startswith("kw_") else 7
        raw = context.args[0][prefix_len:]
        kw = ""
        if raw.startswith("b64_"):
            try:
                import base64
                b64_str = raw[4:]
                padding = "=" * (-len(b64_str) % 4)
                kw = base64.urlsafe_b64decode(b64_str + padding).decode("utf-8")
            except Exception:
                kw = ""
        else:
            kw = raw.strip()
        if kw:
            if context and getattr(context, "user_data", None) is not None:
                context.user_data["teacher_search_query"] = kw
            try:
                from bot.handlers.teachers import show_teachers_list
            except ImportError:
                from handlers.teachers import show_teachers_list
            await show_teachers_list(update, context, page=0, query=kw)
            return

    await send_homepage(update, context)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_browse(update, context)


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_browse(update, context)


from core.rate_limiter import rate_limiter


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        if rate_limiter.is_message_rate_limited(user.id, user.username):
            return
        await db.register_user(
            chat_id=update.effective_chat.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language=user.language_code,
        )

    # Check if text belongs to an active inquiry wizard session (Step 4 notes or Step 2 skip/cancel)
    from inquiry.handlers import on_inquiry_text
    if await on_inquiry_text(update, context):
        return

    # Check if awaiting teacher directory search query
    if context.user_data.get("awaiting_teacher_search") and update.message and update.message.text:
        context.user_data.pop("awaiting_teacher_search", None)
        query = update.message.text.strip()
        context.user_data["teacher_search_query"] = query
        try:
            from bot.handlers.teachers import show_teachers_list
        except ImportError:
            from handlers.teachers import show_teachers_list
        await show_teachers_list(update, context, page=0, query=query)
        return

    if context.user_data.get("awaiting_subkw") and update.message and update.message.text:
        target_mode = context.user_data.pop("awaiting_subkw")
        sub_val = update.message.text.strip()
        if target_mode == "browse":
            state = context.user_data.setdefault("browse", {})
            state["sub_query"] = sub_val
            state["page"] = 0
            from handlers.browse import _show_browse_results
            await _show_browse_results(update, context, 0)
        else:
            context.user_data["sub_query"] = sub_val
            context.user_data["page"] = 0
            query = context.user_data.get("search_query")
            if query:
                await _send_results(update, context, query, 0)
            else:
                await cmd_search(update, context)
        return

    await send_homepage(update, context)


async def on_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.callback_query.data:
        return
    user = update.effective_user
    if user and rate_limiter.is_callback_rate_limited(user.id, user.username):
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        return

    data = update.callback_query.data
    val = data.split(":")[1] if ":" in data else ""
    if val == "noop":
        await update.callback_query.answer()
        return

    page = context.user_data.get("page", 0)
    view_mode = context.user_data.get("view_mode", "card")
    sort_mode = context.user_data.get("sort_mode", "score")

    if val == "subkw":
        context.user_data["awaiting_subkw"] = "search"
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(
                "🔎 <b>请输入需要在当前结果中筛选的二次关键词：</b>\n<i>直接发送文字即可，例如：输入 \"静安\" 或 \"包夜\"。</i>",
                parse_mode="HTML"
            )
        await update.callback_query.answer()
        return
    elif val == "clearsubkw":
        context.user_data.pop("sub_query", None)
        context.user_data["page"] = 0
        query = context.user_data.get("search_query")
        if query:
            await _send_results(update, context, query, 0, edit=True)
        await update.callback_query.answer()
        return
    elif val == "tvm":
        context.user_data["view_mode"] = "compact" if view_mode == "card" else "card"
    elif val == "tsort":
        context.user_data["sort_mode"] = "recent" if sort_mode == "score" else "score"
    else:
        try:
            page = int(val)
            context.user_data["page"] = page
        except ValueError:
            pass

    mode = context.user_data.get("mode", "search")

    try:
        if mode == "recent":
            await _send_recent(update, context, page, edit=True)
        else:
            query = context.user_data.get("search_query")
            if not query:
                await update.callback_query.answer(
                    t("search_expired", _lang(update)), show_alert=True
                )
                return
            await _send_results(update, context, query, page, edit=True)
    finally:
        try:
            await update.callback_query.answer()
        except Exception:
            pass

