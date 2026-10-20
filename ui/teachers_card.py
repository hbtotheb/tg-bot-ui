from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

BOT_DIR = Path(__file__).parent.parent
DEFAULT_PLACEHOLDER_PHOTO = BOT_DIR / "assets" / "placeholder_teacher.jpg"
DIVIDER = "────────────────────────"


def safe_close_html(text: str) -> str:
    """Ensure all opened HTML tags in a text snippet are properly closed."""
    tokens = re.findall(r"<(/?)([a-z]+)[^>]*>", text)
    stack: list[str] = []
    for slash, tag in tokens:
        if not slash:
            stack.append(tag)
        elif stack and stack[-1] == tag:
            stack.pop()
    while stack:
        text += f"</{stack.pop()}>"
    return text


def safe_truncate_html(text: str, max_chars: int = 1000) -> str:
    """
    Safely truncate HTML text without cutting inside tags or leaving unbalanced tags.
    Ensures no malformed partial tags like '</a', '<a href="...', '<b', etc.
    """
    if len(text) <= max_chars:
        return safe_close_html(text)

    truncated = text[: max_chars - 1]
    last_open = truncated.rfind("<")
    last_close = truncated.rfind(">")
    if last_open > last_close:
        truncated = truncated[:last_open]

    truncated = truncated.rstrip() + "…"
    return safe_close_html(truncated)


def get_teacher_photo(teacher: dict) -> str:
    """Return local path to teacher photo, strictly falling back to placeholder if missing or group avatar."""
    path = teacher.get("photo_path")
    if path:
        p = Path(path)
        if p.exists() and p.is_file():
            try:
                from extractor.photo_filter import is_blacklisted_or_group_photo
                if not is_blacklisted_or_group_photo(p):
                    return str(p)
            except Exception:
                return str(p)
    return str(DEFAULT_PLACEHOLDER_PHOTO)



def format_teacher_card(
    teacher: dict, index: int, total: int, back_callback: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    """Format single teacher profile as a sleek, Tinder-like swipe card with interactive controls."""
    name = html.escape(teacher.get("name") or teacher.get("canonical_name") or "精选老师")

    # Teacher intro post link (channel post)
    raw_post_link = teacher.get("teacher_post_link")
    post_link = raw_post_link.strip() if raw_post_link and isinstance(raw_post_link, str) else None
    valid_post_url = bool(post_link and post_link.startswith(("http://", "https://", "tg://")))

    if valid_post_url:
        name_line = f'💃 <a href="{html.escape(post_link)}"><b>{name}</b></a>'
    else:
        name_line = f"💃 <b>{name}</b>"

    # Location
    loc_parts = []
    if teacher.get("city") or teacher.get("canonical_city"):
        loc_parts.append(teacher.get("city") or teacher.get("canonical_city"))
    if teacher.get("district"):
        loc_parts.append(teacher["district"])
    if teacher.get("landmark"):
        loc_parts.append(teacher["landmark"])
    loc_str = " · ".join(html.escape(p) for p in loc_parts) if loc_parts else "未登记具体位置"

    # Price
    def _fmt_price_val(val: Any) -> str:
        v = float(val)
        return str(int(v)) if v.is_integer() else f"{v:.1f}"

    price = teacher.get("price")
    price_p = teacher.get("price_p")
    price_pp = teacher.get("price_pp")

    valid_p = price_p if (price_p and float(price_p) > 0) else (price if (price and float(price) > 0) else None)
    valid_pp = price_pp if (price_pp and float(price_pp) > 0) else None

    # Inversion sanity check
    if valid_p and valid_pp and float(valid_p) > float(valid_pp):
        valid_p, valid_pp = valid_pp, valid_p

    if valid_p and valid_pp:
        price_str = f"{_fmt_price_val(valid_p)} / 1P · {_fmt_price_val(valid_pp)} / 2P"
    elif valid_p:
        price_str = f"{_fmt_price_val(valid_p)} / 1P"
    elif valid_pp:
        price_str = f"{_fmt_price_val(valid_pp)} / 2P"
    else:
        price_str = "暂无标价 / 详询"

    # Teacher Summary / Features
    summary_raw = (teacher.get("summary") or "").strip()
    if summary_raw:
        if len(summary_raw) > 120:
            summary_raw = summary_raw[:117] + "..."
        summary_esc = html.escape(summary_raw)
        summary_block = f"💡 <b>评测总结：</b>\n<i>{summary_esc}</i>"
    else:
        tags_raw = teacher.get("tags") or ""
        if tags_raw:
            tags_list = [t.strip() for t in str(tags_raw).replace("，", ",").split(",") if t.strip()]
            tags_str = "  ".join(f"<code>#{html.escape(t)}</code>" for t in tags_list[:6])
            summary_block = f"🏷️ <b>特色印象：</b>\n{tags_str}"
        else:
            summary_block = "💡 <b>评测总结：</b> <i>暂无评测总结</i>"

    # Teacher account link (support @handle or fallback to booking/auth redirect url)
    teacher_account = teacher.get("teacher_account")
    raw_booking = teacher.get("booking_url")
    if teacher_account:
        raw_acc = teacher_account.strip()
        if raw_acc.startswith(("http://", "https://", "tg://")):
            account_url = raw_acc
        else:
            clean_account = raw_acc.lstrip("@")
            account_url = f"https://t.me/{clean_account}" if clean_account else None
    elif raw_booking and isinstance(raw_booking, str) and raw_booking.strip().startswith(("http://", "https://", "tg://")):
        account_url = raw_booking.strip()
    else:
        account_url = None

    # Review count
    review_count_val = teacher.get("review_count")
    if review_count_val is not None:
        try:
            review_count = int(review_count_val)
        except (ValueError, TypeError):
            review_count = 0
    else:
        raw_revs = teacher.get("reviews")
        if isinstance(raw_revs, list):
            review_count = len(raw_revs)
        elif isinstance(raw_revs, str):
            try:
                import json
                review_count = len(json.loads(raw_revs))
            except Exception:
                review_count = 0
        else:
            review_count = 0

    lines = [
        name_line,
    ]

    lines.extend([
        f"📍 <b>所在地区：</b> {loc_str}",
        f"💰 <b>参考收费：</b> <b>{price_str}</b>",
    ])

    status = teacher.get("status")
    status_reason = teacher.get("status_reason")
    if status == "inactive":
        if status_reason == "post_resting":
            lines.append("⏸ <b>状态提示：</b> <i>频道标注近期休假/暂停开课</i>")
        elif status_reason == "account_deleted":
            lines.append("⚠️ <b>状态提示：</b> <i>电报账号疑似已注销或已改名</i>")
        elif status_reason == "long_inactive":
            lines.append("⏳ <b>状态提示：</b> <i>电报账号长期未登录，可能暂未营业</i>")
        elif status_reason == "post_deleted":
            lines.append("⚠️ <b>状态提示：</b> <i>频道介绍帖已被删除，可能已下架</i>")
        else:
            lines.append("⚠️ <b>状态提示：</b> <i>该老师近期可能暂未开课</i>")

    lines.extend([
        "",
        summary_block,
        f"{DIVIDER}",
    ])

    text = "\n".join(lines)
    if len(text) > 1000:
        text = text[:990] + "…"

    # Tinder-like Buttons
    buttons: list[list[InlineKeyboardButton]] = []

    # Row 1: Swiping Controls (Previous / Next)
    swipe_row: list[InlineKeyboardButton] = []
    if index > 0:
        swipe_row.append(InlineKeyboardButton("⬅️ 上一位", callback_data=f"tc:swipe:{index - 1}"))

    if index < total - 1:
        next_label = "➡️ 下一位 (换一个)" if index > 0 else "➡️ 换一个 / 下一位"
        swipe_row.append(InlineKeyboardButton(next_label, callback_data=f"tc:swipe:{index + 1}"))
    else:
        swipe_row.append(InlineKeyboardButton("🔄 从头重新浏览", callback_data="tc:swipe:0"))

    buttons.append(swipe_row)

    # Row 2: Action Controls (Teacher Contact & Post Link)
    action_row: list[InlineKeyboardButton] = []
    if account_url:
        action_row.append(InlineKeyboardButton("✈️ 老师直联 ↗", url=account_url))
    if valid_post_url and post_link != account_url:
        action_row.append(InlineKeyboardButton("🔗 老师介绍帖 ↗", url=post_link))

    if action_row:
        buttons.append(action_row)

    # Row 3: Reviews Button (indicates review count)
    tid = teacher.get("id") or 0
    buttons.append([InlineKeyboardButton(f"💬 查看所有评测 ({review_count} 篇)", callback_data=f"tc:rev:{tid}:{index}")])

    # Row 4: Navigation Back to Main Menu & List Mode
    nav_row: list[InlineKeyboardButton] = []
    if back_callback:
        nav_row.append(InlineKeyboardButton("🔙 返回老师列表", callback_data=back_callback))
    nav_row.append(InlineKeyboardButton("🏠 返回机器人首页", callback_data="feat:start"))
    buttons.append(nav_row)

    return text, InlineKeyboardMarkup(buttons)


def format_empty_card() -> tuple[str, InlineKeyboardMarkup]:
    """Render empty state when no teachers are present in the database."""
    text = (
        "<blockquote>暂无评测聚合的老师数据，系统正在持续索引和分析中...</blockquote>\n\n"
        "💡 <i>请稍后再试或通过主菜单检索其他频道消息。</i>"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 返回首页", callback_data="feat:start")]])
    return text, markup


def clean_review_snippet(raw_text: str, max_len: int = 65) -> str:
    """Extract clean preview snippet from review content, skipping template headers."""
    if not raw_text:
        return ""
    # Try finding the review feedback section (after colon or newline, e.g. 体验细节：...)
    m = re.search(r"(?:体验细节|评测细节|作业反馈|细节|评价|体验)(?:[：:]|\s*\n+)\s*(.+)", raw_text, re.DOTALL)
    if m:
        text_body = m.group(1).strip()
    else:
        parts = re.split(r"[-—=]{4,}", raw_text)
        if len(parts) > 1:
            text_body = parts[-1].strip()
        else:
            text_body = raw_text.strip()

    clean = " ".join(text_body.split())
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)
    if len(clean) > max_len:
        clean = clean[: max_len - 1] + "…"
    return clean


def format_teacher_reviews(
    teacher: dict,
    reviews: list[dict],
    from_index: int,
    page: int = 0,
    page_size: int = 6,
    bot_username: str | None = None,
    max_chars: int = 1000,
    back_callback: str | None = None,
    review_callback_prefix: str = "tc",
) -> tuple[str, InlineKeyboardMarkup]:
    """Render user reviews overview list with clean reviewer metadata and inline redirect link."""
    name = html.escape(teacher.get("name") or teacher.get("canonical_name") or "精选老师")
    tid = teacher.get("id") or 0
    total_reviews = len(reviews)
    total_pages = max(1, (total_reviews + page_size - 1) // page_size)
    current_page = max(0, min(page, total_pages - 1))
    page_reviews = reviews[current_page * page_size : (current_page + 1) * page_size]

    if total_pages > 1:
        title_line = f"📝 <b>【{name}】的全部评测 ({total_reviews} 篇)</b> <i>[{current_page + 1}/{total_pages}页]</i>"
    else:
        title_line = f"📝 <b>【{name}】的全部评测 ({total_reviews} 篇)</b>"

    lines = [
        title_line,
        f"{DIVIDER}",
    ]

    if not reviews:
        lines.append("<blockquote>暂未获取到该老师的历史评测记录。</blockquote>")
    else:
        for idx, r in enumerate(page_reviews):
            review_num = current_page * page_size + idx + 1
            rid = r.get("id") or 0

            # 1. Reviewer Name & Username
            username = (r.get("username") or "").strip().lstrip("@")
            first_name = (r.get("first_name") or "").strip()
            if first_name and username:
                user_str = f"{html.escape(first_name)} (@{html.escape(username)})"
            elif username:
                user_str = f"@{html.escape(username)}"
            elif first_name:
                user_str = html.escape(first_name)
            else:
                user_str = "匿名用户"

            # 2. Group / Channel Name
            chat_title = (r.get("chat_title") or "").strip()
            group_str = html.escape(chat_title[:20]) if chat_title else ""

            # 3. Review Date
            date_str = ""
            raw_date = r.get("date")
            if raw_date:
                try:
                    if isinstance(raw_date, (int, float)) or (isinstance(raw_date, str) and raw_date.isdigit()):
                        dt = datetime.fromtimestamp(int(raw_date))
                        date_str = dt.strftime("%Y-%m-%d")
                    elif isinstance(raw_date, str):
                        date_str = raw_date[:10]
                except Exception:
                    date_str = str(raw_date)[:10]

            # 4. Inline redirect link:
            # If bot_username is provided, link to in-bot subpage deep link:
            # https://t.me/{bot_username}?start=rdtl_{tid}_{rid}_{from_index}_{current_page}_{review_num}
            # Or irdtl for inquiry flow
            raw_msg_link = (r.get("message_link") or "").strip()
            valid_msg_link = raw_msg_link if raw_msg_link.startswith(("http://", "https://", "tg://")) else ""

            detail_url = ""
            if bot_username:
                clean_bot = bot_username.strip().lstrip("@")
                detail_prefix = "irdtl" if review_callback_prefix == "inq" else "rdtl"
                detail_url = f"https://t.me/{clean_bot}?start={detail_prefix}_{tid}_{rid}_{from_index}_{current_page}_{review_num}"
            elif valid_msg_link:
                detail_url = valid_msg_link

            parts_line = [f"<b>{review_num}. 👤 {user_str}</b>"]
            if group_str:
                parts_line.append(f"👥 {group_str}")
            if date_str:
                parts_line.append(f"📅 <i>{date_str}</i>")
            if detail_url:
                parts_line.append(f'<a href="{html.escape(detail_url)}">[详情 ↗]</a>')

            lines.append(" · ".join(parts_line))

    lines.append(f"{DIVIDER}")
    text = safe_truncate_html("\n".join(lines), max_chars=max_chars)

    keyboard_rows: list[list[InlineKeyboardButton]] = []

    # Pagination controls (if multiple pages exist)
    if total_pages > 1:
        page_buttons: list[InlineKeyboardButton] = []
        if current_page > 0:
            page_buttons.append(
                InlineKeyboardButton("⬅️ 上一页", callback_data=f"{review_callback_prefix}:rev:{tid}:{from_index}:{current_page - 1}")
            )
        page_buttons.append(
            InlineKeyboardButton(f"📄 {current_page + 1}/{total_pages}", callback_data="tc:noop")
        )
        if current_page < total_pages - 1:
            page_buttons.append(
                InlineKeyboardButton("下一页 ➡️", callback_data=f"{review_callback_prefix}:rev:{tid}:{from_index}:{current_page + 1}")
            )
        keyboard_rows.append(page_buttons)

    # Action Controls (Teacher Contact & Post Link)
    action_row: list[InlineKeyboardButton] = []
    teacher_account = teacher.get("teacher_account")
    raw_booking = teacher.get("booking_url")
    if teacher_account:
        raw_acc = teacher_account.strip()
        if raw_acc.startswith(("http://", "https://", "tg://")):
            account_url = raw_acc
        else:
            clean_account = raw_acc.lstrip("@")
            account_url = f"https://t.me/{clean_account}" if clean_account else None
    elif raw_booking and isinstance(raw_booking, str) and raw_booking.strip().startswith(("http://", "https://", "tg://")):
        account_url = raw_booking.strip()
    else:
        account_url = None

    if account_url:
        action_row.append(InlineKeyboardButton("✈️ 老师直联 ↗", url=account_url))

    raw_post_link = teacher.get("teacher_post_link")
    post_link = raw_post_link.strip() if raw_post_link and isinstance(raw_post_link, str) else None
    if post_link and post_link.startswith(("http://", "https://", "tg://")) and post_link != account_url:
        action_row.append(InlineKeyboardButton("🔗 老师介绍帖 ↗", url=post_link))

    if action_row:
        keyboard_rows.append(action_row)

    # Navigation Controls
    back_cb = back_callback or f"{review_callback_prefix}:swipe:{from_index}"
    keyboard_rows.append([
        InlineKeyboardButton("🔙 返回老师卡片", callback_data=back_cb),
        InlineKeyboardButton("🏠 返回机器人首页", callback_data="feat:start"),
    ])

    return text, InlineKeyboardMarkup(keyboard_rows)


def format_review_detail(
    teacher: dict,
    review: dict,
    review_num: int,
    from_index: int,
    page: int = 0,
    max_chars: int = 1000,
    back_callback: str | None = None,
    review_list_callback: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Render single review full content subpage with direct link to original post."""
    name = html.escape(teacher.get("name") or teacher.get("canonical_name") or "精选老师")

    # 1. Reviewer Name & Username
    username = (review.get("username") or "").strip().lstrip("@")
    first_name = (review.get("first_name") or "").strip()
    if first_name and username:
        user_str = f"{html.escape(first_name)} (@{html.escape(username)})"
    elif username:
        user_str = f"@{html.escape(username)}"
    elif first_name:
        user_str = html.escape(first_name)
    else:
        user_str = "匿名用户"

    # 2. Group / Channel Name
    chat_title = (review.get("chat_title") or "").strip()
    group_str = html.escape(chat_title) if chat_title else "未知群组/频道"

    # 3. Review Date
    date_str = ""
    raw_date = review.get("date")
    if raw_date:
        try:
            if isinstance(raw_date, (int, float)) or (isinstance(raw_date, str) and raw_date.isdigit()):
                dt = datetime.fromtimestamp(int(raw_date))
                date_str = dt.strftime("%Y-%m-%d")
            elif isinstance(raw_date, str):
                date_str = raw_date[:10]
        except Exception:
            date_str = str(raw_date)[:10]

    # 4. Link to Original Post
    raw_msg_link = (review.get("message_link") or "").strip()
    valid_msg_link = raw_msg_link if raw_msg_link.startswith(("http://", "https://", "tg://")) else ""

    title_line = f"📝 <b>【{name}】· 评测全文 (#{review_num})</b>"
    lines = [
        title_line,
        f"{DIVIDER}",
        f"👤 <b>评测人：</b> {user_str}",
        f"👥 <b>来源群组：</b> {group_str}",
    ]
    if date_str:
        lines.append(f"📅 <b>评测日期：</b> <i>{date_str}</i>")

    rating = review.get("rating")
    if rating:
        try:
            r_val = float(rating)
            if r_val > 0:
                lines.append(f"⭐ <b>体验评分：</b> <b>{r_val:.1f}</b> / 5.0")
        except (ValueError, TypeError):
            pass

    lines.extend([
        f"{DIVIDER}",
        "💬 <b>评测内容：</b>",
    ])

    base_text = "\n".join(lines) + f"\n{DIVIDER}\n"
    avail_budget = max(200, max_chars - len(base_text) - 40)

    content = str(review.get("content") or "").strip()
    if content:
        if len(content) > avail_budget:
            content = content[: avail_budget - 1] + "…"
        lines.append(f"<blockquote>{html.escape(content)}</blockquote>")
    else:
        lines.append("<blockquote><i>（暂无评测文字内容）</i></blockquote>")

    lines.append(f"{DIVIDER}")
    text = safe_truncate_html("\n".join(lines), max_chars=max_chars)

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    tid = teacher.get("id") or 0

    # Row 1: Link to original post
    if valid_msg_link:
        keyboard_rows.append([InlineKeyboardButton("🔗 查看评测原帖 ↗", url=valid_msg_link)])

    # Row 2: Return to reviews list
    rev_list_cb = review_list_callback or f"tc:rev:{tid}:{from_index}:{page}"
    keyboard_rows.append([InlineKeyboardButton("🔙 返回评测列表", callback_data=rev_list_cb)])

    # Row 3: Return to teacher card & home
    card_cb = back_callback or f"tc:swipe:{from_index}"
    keyboard_rows.append([
        InlineKeyboardButton("🔙 返回老师卡片", callback_data=card_cb),
        InlineKeyboardButton("🏠 返回机器人首页", callback_data="feat:start"),
    ])

    return text, InlineKeyboardMarkup(keyboard_rows)
