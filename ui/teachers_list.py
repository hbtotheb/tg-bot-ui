from __future__ import annotations

import html
import os
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 8
DIVIDER = "────────────────────────"
NUM_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]


def format_teachers_list(
    teachers: list[dict[str, Any]],
    page: int,
    total: int,
    page_size: int = PAGE_SIZE,
    query: str | None = None,
    sort_by: str = "rank",
    bot_username: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Format paginated teacher directory (8 profiles per page) with clickable profile links and search controls."""
    total_pages = max(1, (total + page_size - 1) // page_size)
    current_page = max(0, min(page, total_pages - 1))

    clean_bot = (bot_username or "").strip().lstrip("@")
    if not clean_bot:
        clean_bot = os.getenv("BOT_USERNAME", "tg_search_bot").strip().lstrip("@")

    # Header
    clean_query = query.strip() if query else ""
    if clean_query:
        title = (
            f"📋 <b>老师名录 · 搜索结果 (共 {total} 位)</b> · <i>第 {current_page + 1}/{total_pages} 页</i>\n"
            f"🔍 <b>当前检索：</b> <code>{html.escape(clean_query)}</code>"
        )
    else:
        title = f"📋 <b>精选老师名录 (共 {total} 位)</b> · <i>第 {current_page + 1}/{total_pages} 页</i>"

    lines = [title, DIVIDER]

    if not teachers:
        if clean_query:
            lines.append(
                f"<blockquote>未找到与 “<b>{html.escape(clean_query)}</b>” 相关的老师。\n\n"
                "💡 建议尝试缩短搜索词，或按区域商圈检索（如“静安”、“浦东”）。</blockquote>"
            )
        else:
            lines.append("<blockquote>暂无已收录的老师数据。</blockquote>")
    else:
        item_blocks = []
        for idx, teacher in enumerate(teachers):
            num_emoji = NUM_EMOJIS[idx] if idx < len(NUM_EMOJIS) else f"{idx + 1}."
            name = html.escape(teacher.get("name") or teacher.get("canonical_name") or "精选老师")
            rating = teacher.get("rating") or 0.0
            review_count = teacher.get("review_count") or 0
            if not isinstance(review_count, int):
                try:
                    review_count = int(review_count)
                except Exception:
                    review_count = 0

            # In-chat deep link to open teacher photo card
            tid = teacher.get("id") or 0
            detail_url = f"https://t.me/{clean_bot}?start=tc_{tid}_{current_page}"

            raw_post_link = teacher.get("teacher_post_link")
            post_link = raw_post_link.strip() if raw_post_link and isinstance(raw_post_link, str) else None
            valid_post_url = bool(post_link and post_link.startswith(("http://", "https://", "tg://")))

            # Location
            loc_parts = []
            if teacher.get("city") or teacher.get("canonical_city"):
                loc_parts.append(teacher.get("city") or teacher.get("canonical_city"))
            if teacher.get("district"):
                loc_parts.append(teacher["district"])
            if teacher.get("landmark"):
                loc_parts.append(teacher["landmark"])
            loc_str = " · ".join(html.escape(p) for p in loc_parts) if loc_parts else "未标明区域"

            # Price
            def _fmt_price_val(val: Any) -> str:
                v = float(val)
                return str(int(v)) if v.is_integer() else f"{v:.1f}"

            price = teacher.get("price")
            price_p = teacher.get("price_p")
            price_pp = teacher.get("price_pp")
            valid_p = price_p if (price_p and float(price_p) > 0) else (price if (price and float(price) > 0) else None)
            valid_pp = price_pp if (price_pp and float(price_pp) > 0) else None

            if valid_p and valid_pp and float(valid_p) > float(valid_pp):
                valid_p, valid_pp = valid_pp, valid_p

            if valid_p and valid_pp:
                price_str = f"¥{_fmt_price_val(valid_p)}/1P · ¥{_fmt_price_val(valid_pp)}/2P"
            elif valid_p:
                price_str = f"¥{_fmt_price_val(valid_p)}/1P"
            elif valid_pp:
                price_str = f"¥{_fmt_price_val(valid_pp)}/2P"
            else:
                price_str = "详询"

            # Summary / Tags
            summary_raw = (teacher.get("summary") or "").strip()
            tags_raw = teacher.get("tags") or ""
            feature_line = ""
            if tags_raw:
                tags_list = [t.strip() for t in str(tags_raw).replace("，", ",").split(",") if t.strip()]
                if tags_list:
                    feature_line = " ".join(f"<code>#{html.escape(t)}</code>" for t in tags_list[:3])
            if not feature_line and summary_raw:
                feature_snippet = summary_raw[:35] + "…" if len(summary_raw) > 35 else summary_raw
                feature_line = f"<i>{html.escape(feature_snippet)}</i>"

            title_parts = [
                f'{num_emoji} 💃 <a href="{html.escape(detail_url)}"><b>{name}</b></a> (⭐ {rating:.1f} · {review_count}篇评测)',
                f'<a href="{html.escape(detail_url)}">[查看 ➔]</a>',
            ]
            if valid_post_url:
                title_parts.append(f'<a href="{html.escape(post_link)}">[介绍帖 ↗]</a>')

            item_lines = [
                " ".join(title_parts),
                f"   📍 {loc_str} | 💰 {price_str}",
            ]
            if feature_line:
                item_lines.append(f"   🏷️ {feature_line}")

            item_blocks.append("\n".join(item_lines))

        lines.append("\n\n".join(item_blocks))

    lines.append(DIVIDER)
    if teachers:
        lines.append("💡 <i>点击老师姓名或 [查看 ➔] 即可直接打开相片与评测资料</i>")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"

    # Keyboard layout without individual jump buttons
    keyboard: list[list[InlineKeyboardButton]] = []

    # Pagination row
    if total_pages > 1:
        page_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            page_row.append(InlineKeyboardButton("◀ 上一页", callback_data=f"tl:page:{current_page - 1}"))
        page_row.append(InlineKeyboardButton(f"📄 {current_page + 1}/{total_pages} ({total}位)", callback_data="tl:noop"))
        if current_page < total_pages - 1:
            page_row.append(InlineKeyboardButton("下一页 ▶", callback_data=f"tl:page:{current_page + 1}"))
        keyboard.append(page_row)

    # Search & Clear search row
    search_row: list[InlineKeyboardButton] = []
    if clean_query:
        search_row.append(InlineKeyboardButton("🔍 重新搜索", callback_data="tl:search"))
        search_row.append(InlineKeyboardButton("✕ 清除搜索", callback_data="tl:clearsearch"))
    else:
        search_row.append(InlineKeyboardButton("🔍 搜索老师", callback_data="tl:search"))
    keyboard.append(search_row)

    # Navigation row
    keyboard.append([
        InlineKeyboardButton("🏠 返回首页", callback_data="feat:start"),
    ])

    return text, InlineKeyboardMarkup(keyboard)


def format_teacher_search_prompt() -> tuple[str, InlineKeyboardMarkup]:
    """Render search prompt inviting user to type search keywords."""
    text = (
        "🔍 <b>搜索老师名录</b>\n"
        f"{DIVIDER}\n"
        "请在输入框发送老师姓名、别名、地区商圈（如“静安”、“浦东”）或特色偏好：\n\n"
        "💡 <i>直接发送文字即可检索，或点击下方按钮返回名录：</i>"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ 返回老师列表", callback_data="tl:page:0")],
        [InlineKeyboardButton("🏠 返回机器人首页", callback_data="feat:start")],
    ])
    return text, markup
