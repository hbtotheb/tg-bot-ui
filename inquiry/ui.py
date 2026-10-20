from __future__ import annotations

import html
from typing import Any
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .state import InquirySession

DIVIDER = "────────────────────────"


def _make_edit_link(session: InquirySession, step: str, text: str) -> str:
    """Generate clickable in-chat deep link to jump directly to edit an answer."""
    clean_text = html.escape(text)
    bot_user = (session.bot_username or "").strip().lstrip("@")
    if not bot_user:
        bot_user = "tg_search_bot"
    return f'<a href="https://t.me/{bot_user}?start=inq_{step}">{clean_text} ✏️</a>'


def render_look_step(teacher: dict[str, Any] | None, session: InquirySession) -> tuple[str, InlineKeyboardMarkup]:
    """Render Question #1: Preferred Look (Young / Mature / Pure / Custom)."""
    t = teacher or {}
    t_name = t.get("name") or t.get("canonical_name")
    target_line = f"💃 <b>目标老师：</b> <b>{html.escape(t_name)}</b>\n\n" if t_name else ""

    curr_selected = ""
    if session.preferred_look:
        look_link = _make_edit_link(session, "look", session.preferred_look)
        curr_selected = f"🌸 <b>当前已选：</b> {look_link}\n\n"

    text = (
        f"🌸 <b>需求定制（第 1/5 题：外貌风格）</b>\n"
        f"{DIVIDER}\n"
        f"{target_line}"
        f"{curr_selected}"
        f"<b>请选择您偏好的外貌风格：</b>\n"
        f"<i>💡 可点击下方快捷选项，或直接在输入框打字发送：</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("🌸 青春嫩妹", callback_data="inq:look:青春嫩妹"),
            InlineKeyboardButton("💃 成熟御姐", callback_data="inq:look:成熟御姐"),
        ],
        [
            InlineKeyboardButton("🌿 清纯邻家", callback_data="inq:look:清纯邻家"),
            InlineKeyboardButton("⏭️ 均可不限", callback_data="inq:look:不限风格"),
        ],
    ]

    if session.confirmed_once:
        buttons.append([
            InlineKeyboardButton("↩️ 返回确认清单", callback_data="inq:goto:confirm"),
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])

    return text, InlineKeyboardMarkup(buttons)


def render_body_step(teacher: dict[str, Any] | None, session: InquirySession) -> tuple[str, InlineKeyboardMarkup]:
    """Render Question #2: Preferred Body Type (Skinny / Busty / Tall / Petite / Custom)."""
    look_val = session.preferred_look or "不限"
    look_link = _make_edit_link(session, "look", look_val)

    curr_selected = ""
    if session.preferred_body:
        body_link = _make_edit_link(session, "body", session.preferred_body)
        curr_selected = f"👙 <b>当前已选：</b> {body_link}\n\n"

    text = (
        f"👙 <b>需求定制（第 2/5 题：身材体型）</b>\n"
        f"{DIVIDER}\n"
        f"🌸 <b>已选外貌：</b> {look_link}\n\n"
        f"{curr_selected}"
        f"<b>请选择您偏好的身材体态：</b>\n"
        f"<i>💡 可点击下方快捷选项，或直接在输入框打字发送：</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("🩰 苗条纤细", callback_data="inq:body:苗条纤细"),
            InlineKeyboardButton("🍈 丰满有料", callback_data="inq:body:丰满有料"),
        ],
        [
            InlineKeyboardButton("👠 高挑长腿", callback_data="inq:body:高挑长腿"),
            InlineKeyboardButton("🍑 微胖肉感", callback_data="inq:body:微胖肉感"),
        ],
        [
            InlineKeyboardButton("🐰 娇小可爱", callback_data="inq:body:娇小可爱"),
            InlineKeyboardButton("⏭️ 均可不限", callback_data="inq:body:不限身材"),
        ],
    ]

    if session.confirmed_once:
        buttons.append([
            InlineKeyboardButton("↩️ 返回确认清单", callback_data="inq:goto:confirm"),
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])

    return text, InlineKeyboardMarkup(buttons)


def render_price_step(teacher: dict[str, Any] | None, session: InquirySession) -> tuple[str, InlineKeyboardMarkup]:
    """Render Question #3: Preferred Price Range (Select Range with restricted chat input, 300-step 1P granularity)."""
    look_val = session.preferred_look or "不限"
    body_val = session.preferred_body or "不限"
    look_link = _make_edit_link(session, "look", look_val)
    body_link = _make_edit_link(session, "body", body_val)

    curr_selected = ""
    if session.preferred_price:
        price_link = _make_edit_link(session, "price", session.preferred_price)
        curr_selected = f"💰 <b>当前已选：</b> {price_link}\n\n"

    text = (
        f"💰 <b>需求定制（第 3/5 题：单次预算 · 1P）</b>\n"
        f"{DIVIDER}\n"
        f"🌸 <b>外貌：</b> {look_link} | 👙 <b>身材：</b> {body_link}\n\n"
        f"{curr_selected}"
        f"<b>请选择您的单次预算区间（以 1P 为准，按 300 梯度细分）：</b>\n"
        f"<i>💡 为保证匹配精准度，请直接点击下方预设选项（限制自由文本）：</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("💸 600 以下 (1P)", callback_data="inq:price:600以下(1P)"),
            InlineKeyboardButton("💵 600 - 900 (1P)", callback_data="inq:price:600-900(1P)"),
        ],
        [
            InlineKeyboardButton("💴 900 - 1200 (1P)", callback_data="inq:price:900-1200(1P)"),
            InlineKeyboardButton("💶 1200 - 1500 (1P)", callback_data="inq:price:1200-1500(1P)"),
        ],
        [
            InlineKeyboardButton("💷 1500 - 1800 (1P)", callback_data="inq:price:1500-1800(1P)"),
            InlineKeyboardButton("💎 1800 以上 (1P)", callback_data="inq:price:1800以上(1P)"),
        ],
        [
            InlineKeyboardButton("⏭️ 均可不限", callback_data="inq:price:不限预算"),
        ],
    ]

    if session.confirmed_once:
        buttons.append([
            InlineKeyboardButton("↩️ 返回确认清单", callback_data="inq:goto:confirm"),
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])

    return text, InlineKeyboardMarkup(buttons)


def render_value_step(teacher: dict[str, Any] | None, session: InquirySession) -> tuple[str, InlineKeyboardMarkup]:
    """Render Question #4: What You Value Most (Service / Price / Face / Body / Custom)."""
    look_val = session.preferred_look or "不限"
    body_val = session.preferred_body or "不限"
    price_val = session.preferred_price or "不限"
    look_link = _make_edit_link(session, "look", look_val)
    body_link = _make_edit_link(session, "body", body_val)
    price_link = _make_edit_link(session, "price", price_val)

    curr_selected = ""
    if session.value_most:
        val_link = _make_edit_link(session, "val", session.value_most)
        curr_selected = f"💎 <b>当前已选：</b> {val_link}\n\n"

    text = (
        f"💎 <b>需求定制（第 4/5 题：核心侧重点）</b>\n"
        f"{DIVIDER}\n"
        f"🌸 <b>外貌：</b> {look_link} | 👙 <b>身材：</b> {body_link} | 💰 <b>预算：</b> {price_link}\n\n"
        f"{curr_selected}"
        f"<b>请选择您最看重的方面：</b>\n"
        f"<i>💡 可点击下方快捷选项，或直接在输入框打字发送：</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("💆 服务配合", callback_data="inq:val:服务配合"),
            InlineKeyboardButton("🥰 女友感", callback_data="inq:val:女友感"),
        ],
        [
            InlineKeyboardButton("👧 颜值容貌", callback_data="inq:val:颜值容貌"),
            InlineKeyboardButton("👙 身材体态", callback_data="inq:val:身材体态"),
        ],
        [
            InlineKeyboardButton("💰 高性价比", callback_data="inq:val:高性价比"),
            InlineKeyboardButton("⚖️ 综合均衡", callback_data="inq:val:综合均衡"),
        ],
    ]

    if session.confirmed_once:
        buttons.append([
            InlineKeyboardButton("↩️ 返回确认清单", callback_data="inq:goto:confirm"),
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ])

    return text, InlineKeyboardMarkup(buttons)


def render_map_step(teacher: dict[str, Any] | None, session: InquirySession) -> tuple[str, ReplyKeyboardMarkup]:
    """Render Question #5: Map pin / geo location."""
    t = teacher or {}
    t_name = t.get("name") or t.get("canonical_name")
    target_block = ""
    if t_name:
        t_loc_parts = list(
            filter(None, [t.get("city") or t.get("canonical_city"), t.get("district"), t.get("landmark")])
        )
        t_loc_str = " · ".join(html.escape(p) for p in t_loc_parts) if t_loc_parts else "未标明常驻商圈"
        target_block = f"💃 <b>目标老师：</b> <b>{html.escape(t_name)}</b>\n📌 <b>常驻参考：</b> {t_loc_str}\n\n"

    look_val = session.preferred_look or "不限"
    body_val = session.preferred_body or "不限"
    price_val = session.preferred_price or "不限"
    val_val = session.value_most or "综合体验"
    look_link = _make_edit_link(session, "look", look_val)
    body_link = _make_edit_link(session, "body", body_val)
    price_link = _make_edit_link(session, "price", price_val)
    val_link = _make_edit_link(session, "val", val_val)

    text = (
        f"📍 <b>需求定制（第 5/5 题：设置地理位置）</b>\n"
        f"{DIVIDER}\n"
        f"🌸 <b>外貌：</b> {look_link} | 👙 <b>身材：</b> {body_link} | 💰 <b>预算(1P)：</b> {price_link} | 💎 <b>侧重：</b> {val_link}\n\n"
        f"{target_block}"
        f"💡 <b>请选择或输入您的位置要求：</b>\n"
        f"• 点击下方按钮快捷选择区域，或发送当前位置\n"
        f"• 直接在输入框发送其他商圈/地标（如：陆家嘴、徐家汇）\n"
        f"• 若不限距离，请点击 <b>「⏭️ 跳过位置」</b>"
    )

    keyboard = [
        [KeyboardButton("📍 发送当前位置", request_location=True)],
        [KeyboardButton("浦东"), KeyboardButton("闵行"), KeyboardButton("普陀")],
        [KeyboardButton("静安"), KeyboardButton("徐汇"), KeyboardButton("长宁")],
        [KeyboardButton("⏭️ 跳过位置")],
    ]

    if session.confirmed_once:
        keyboard.append([KeyboardButton("↩️ 返回确认清单"), KeyboardButton("❌ 取消匹配")])
    else:
        keyboard.append([KeyboardButton("❌ 取消匹配")])

    return text, ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def render_confirm_step(teacher: dict[str, Any] | None, session: InquirySession) -> tuple[str, InlineKeyboardMarkup]:
    """Render confirmation review screen summarizing all 5 choices with in-chat edit links and final submit button."""
    t = teacher or {}
    t_name = t.get("name") or t.get("canonical_name")
    target_line = f"💃 <b>目标老师：</b> <b>{html.escape(t_name)}</b>\n\n" if t_name else ""

    look_val = session.preferred_look or "不限风格"
    body_val = session.preferred_body or "不限身材"
    price_val = session.preferred_price or "不限预算"
    val_val = session.value_most or "综合体验"

    if session.latitude is not None and session.longitude is not None:
        loc_val = f"GPS 定位 ({session.latitude:.2f}, {session.longitude:.2f})"
    elif session.location_text:
        loc_val = session.location_text
    elif session.location_skipped:
        loc_val = "跳过定位（不限距离）"
    else:
        loc_val = "未设置"

    look_link = _make_edit_link(session, "look", look_val)
    body_link = _make_edit_link(session, "body", body_val)
    price_link = _make_edit_link(session, "price", price_val)
    val_link = _make_edit_link(session, "val", val_val)
    loc_link = _make_edit_link(session, "map", loc_val)

    text = (
        f"📋 <b>需求定制确认清单</b>\n"
        f"{DIVIDER}\n"
        f"{target_line}"
        f"请核对您的定制偏好需求，<b>点击对应答案链接可随时修改</b>：\n\n"
        f"1️⃣ 🌸 <b>外貌风格：</b> {look_link}\n"
        f"2️⃣ 👙 <b>身材体态：</b> {body_link}\n"
        f"3️⃣ 💰 <b>单次预算(1P)：</b> {price_link}\n"
        f"4️⃣ 💎 <b>核心侧重：</b> {val_link}\n"
        f"5️⃣ 📍 <b>地理位置：</b> {loc_link}\n"
        f"{DIVIDER}\n"
        f"💡 <i>确认无误后，点击「🚀 确认需求，开始智能匹配」！</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("🚀 确认需求，开始智能匹配", callback_data="inq:submit"),
        ],
        [
            InlineKeyboardButton("❌ 取消匹配", callback_data="inq:cancel"),
        ],
    ]

    return text, InlineKeyboardMarkup(buttons)


def render_inquiry_summary(
    session: InquirySession | dict[str, Any],
    query_info: dict[str, Any],
    total_matched: int,
    current_index: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Render a comprehensive summary after intake form submission, detailing:
    1. User's answered preferences.
    2. Structured return from LLM (keywords, weights distribution, focus area, explanation).
    3. Match outcome statistics and navigation guidance.
    """
    if isinstance(session, dict):
        look_val = session.get("preferred_look") or "不限风格"
        body_val = session.get("preferred_body") or "不限身材"
        price_val = session.get("preferred_price") or "不限预算"
        val_val = session.get("value_most") or "综合体验"
        latitude = session.get("latitude")
        longitude = session.get("longitude")
        location_text = session.get("location_text")
        location_skipped = session.get("location_skipped")
    else:
        look_val = session.preferred_look or "不限风格"
        body_val = session.preferred_body or "不限身材"
        price_val = session.preferred_price or "不限预算"
        val_val = session.value_most or "综合体验"
        latitude = session.latitude
        longitude = session.longitude
        location_text = session.location_text
        location_skipped = session.location_skipped

    if latitude is not None and longitude is not None:
        loc_val = f"GPS 定位 ({latitude:.2f}, {longitude:.2f})"
    elif location_text:
        loc_val = location_text
    elif location_skipped:
        loc_val = "不限距离（跳过定位）"
    else:
        loc_val = "未设置"

    # LLM outputs
    kw_str = query_info.get("keywords") or ""
    kw_display = " ".join(f"#{k}" for k in kw_str.split()) if kw_str else "全维度综合"

    weights = query_info.get("weights") or {}
    w_visual = int(round(weights.get("visual", 0.25) * 100))
    w_body = int(round(weights.get("body", 0.25) * 100))
    w_service = int(round(weights.get("service", 0.35) * 100))
    w_price = int(round(weights.get("price", 0.15) * 100))

    focus_names = {
        "service": "服务配合",
        "visual": "颜值容貌",
        "body": "身材体态",
        "price": "高性价比",
    }
    focus_label = focus_names.get(query_info.get("weight_focus", "service"), "综合实力")
    explanation = query_info.get("explanation") or "已根据您的偏好检索加权匹配。"
    source_label = "AI 大模型深度解析" if query_info.get("source") in ("llm", "predefined") else "规则引擎智能解析"

    lines = [
        "📋 <b>需求定制完成 · AI 智能匹配总结报告</b>",
        f"{DIVIDER}",
        "📝 <b>您的定制偏好需求：</b>",
        f"• 🌸 <b>外貌风格：</b> <code>{html.escape(look_val)}</code>",
        f"• 👙 <b>身材体态：</b> <code>{html.escape(body_val)}</code>",
        f"• 💰 <b>单次预算(1P)：</b> <code>{html.escape(price_val)}</code>",
        f"• 💎 <b>核心侧重：</b> <code>{html.escape(val_val)}</code>",
        f"• 📍 <b>地理位置：</b> <code>{html.escape(loc_val)}</code>",
        "",
        f"🤖 <b>{source_label}结果：</b>",
        f"• 🏷️ <b>提取检索词：</b> <b>{html.escape(kw_display)}</b>",
        f"• ⚖️ <b>核心加权项：</b> <b>【{focus_label}】</b> 优先",
        f"• 📊 <b>多维权重配比：</b> 服务 {w_service}% · 颜值 {w_visual}% · 身材 {w_body}% · 价格 {w_price}%",
        f"• 💡 <b>推荐匹配策略：</b> <i>{html.escape(explanation)}</i>",
        "",
        f"🎯 <b>匹配结果：</b> 成功为您精选推荐 <b>{total_matched}</b> 位高契合度老师！",
        f"{DIVIDER}",
        "👇 <i>点击下方按钮即可浏览推荐老师卡片，在卡片上可随时换人或查看历史评测：</i>",
    ]

    text = "\n".join(lines)
    if len(text) > 1000:
        text = text[:990] + "…"

    button_label = (
        f"💃 立即浏览推荐老师 (1/{total_matched}) ➔"
        if current_index == 0
        else f"💃 返回老师卡片 (第 {current_index + 1}/{total_matched} 位) ➔"
    )

    buttons = [
        [
            InlineKeyboardButton(button_label, callback_data=f"inq:swipe:{current_index}"),
        ],
        [
            InlineKeyboardButton("🔄 重新定制需求", callback_data="inq:start"),
            InlineKeyboardButton("🏠 返回首页", callback_data="feat:start"),
        ],
    ]

    return text, InlineKeyboardMarkup(buttons)


def render_matched_teacher_card(
    teacher: dict[str, Any],
    index: int,
    total: int,
    query_info: dict[str, Any],
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Render a Tinder-like matching swipe card for a teacher found and ranked
    by the LLM query and custom weights.
    """
    name = html.escape(teacher.get("name") or teacher.get("canonical_name") or "精选老师")
    raw_post_link = teacher.get("teacher_post_link")
    post_link = raw_post_link.strip() if raw_post_link and isinstance(raw_post_link, str) else None
    valid_post_url = bool(post_link and post_link.startswith(("http://", "https://", "tg://")))

    if valid_post_url:
        name_line = f'💃 <a href="{html.escape(post_link)}"><b>{name}</b></a>'
    else:
        name_line = f"💃 <b>{name}</b>"

    # Location info
    loc_parts = list(
        filter(
            None,
            [
                teacher.get("city") or teacher.get("canonical_city"),
                teacher.get("district"),
                teacher.get("landmark"),
            ],
        )
    )
    loc_str = " · ".join(html.escape(p) for p in loc_parts) if loc_parts else "未标明地区"

    # Price
    price = teacher.get("price")
    price_str = f"¥{price:g} / 次" if isinstance(price, (int, float)) and price > 0 else "私聊咨询"

    # Rubric group scores
    score_visual = teacher.get("score_visual") or teacher.get("rating_look") or 0.0
    score_body = teacher.get("score_body") or 0.0
    score_service = teacher.get("score_service") or teacher.get("rating_service") or 0.0
    rating = teacher.get("rating") or 0.0

    # Match score
    match_score = teacher.get("_match_score")
    match_tag = f" ⭐ <b>匹配评分：{match_score:.2f}</b>" if match_score else ""

    name_line = f"💃 <b>{name}</b> (综合: <b>{rating:.1f}</b>/5.0){match_tag}"

    # Highlight metrics based on what was focused
    focus = query_info.get("weight_focus")
    highlight_line = ""
    if focus == "service":
        highlight_line = f"💆 <b>服务配合度：</b> <b>{score_service:.1f}</b> / 5.0 (AI 加权优先)"
    elif focus == "visual":
        highlight_line = f"🌸 <b>颜值外貌分：</b> <b>{score_visual:.1f}</b> / 5.0 (AI 加权优先)"
    elif focus == "body":
        highlight_line = f"👙 <b>身材体态分：</b> <b>{score_body:.1f}</b> / 5.0 (AI 加权优先)"
    elif focus == "price":
        highlight_line = f"💰 <b>高性价比推荐：</b> <b>{price_str}</b> (AI 加权优先)"

    # Tags / Summary
    summary = teacher.get("summary") or teacher.get("tags") or teacher.get("keywords") or ""
    summary_block = f"<blockquote>{html.escape(summary[:120])}</blockquote>" if summary else ""

    # Account link (support @handle or fallback to booking/auth redirect url)
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
    review_count = teacher.get("review_count") or 0
    if not isinstance(review_count, int):
        try:
            review_count = int(review_count)
        except Exception:
            review_count = 0

    explanation = html.escape(query_info.get("explanation") or "已根据您的偏好检索加权匹配老师。")

    lines = [
        f"🎯 <b>AI 偏好定制推荐（第 {index + 1} / {total} 位）</b>",
        f"💡 <i>{explanation}</i>",
        DIVIDER,
        name_line,
        f"📍 <b>所在地区：</b> {loc_str}",
        f"💰 <b>参考收费：</b> <b>{price_str}</b>",
    ]
    if highlight_line:
        lines.append(highlight_line)
    lines.extend([
        DIVIDER,
        summary_block,
    ])

    text = "\n".join(lines)
    if len(text) > 1000:
        text = text[:990] + "…"

    # Buttons
    buttons: list[list[InlineKeyboardButton]] = []

    # Row 1: Swiping Controls
    swipe_row: list[InlineKeyboardButton] = []
    if index > 0:
        swipe_row.append(InlineKeyboardButton("⬅️ 上一位", callback_data=f"inq:swipe:{index - 1}"))
    if index < total - 1:
        swipe_row.append(InlineKeyboardButton("➡️ 下一位 (换一个)", callback_data=f"inq:swipe:{index + 1}"))
    elif total > 1:
        swipe_row.append(InlineKeyboardButton("🔄 从头重新浏览", callback_data="inq:swipe:0"))
    if swipe_row:
        buttons.append(swipe_row)

    # Row 2: Direct Contact / Post Link
    action_row: list[InlineKeyboardButton] = []
    if account_url:
        action_row.append(InlineKeyboardButton("✈️ 老师直联 ↗", url=account_url))
    if valid_post_url and post_link != account_url:
        action_row.append(InlineKeyboardButton("🔗 老师介绍帖 ↗", url=post_link))
    if action_row:
        buttons.append(action_row)

    # Row 3: Reviews button - uses inq:rev to preserve inquiry session and matched teachers
    tid = teacher.get("id") or 0
    buttons.append([InlineKeyboardButton(f"💬 查看所有评测 ({review_count} 篇)", callback_data=f"inq:rev:{tid}:{index}")])

    # Row 4: Summary report button
    buttons.append([
        InlineKeyboardButton("📋 查看需求与 AI 总结", callback_data=f"inq:summary:{index}"),
    ])

    # Row 5: Restart & Home buttons
    restart_cb = f"inq:restart:{tid}:0" if tid else "inq:start"
    buttons.append([
        InlineKeyboardButton("🔄 重新测试偏好", callback_data=restart_cb),
        InlineKeyboardButton("🏠 返回机器人首页", callback_data="feat:start"),
    ])

    return text, InlineKeyboardMarkup(buttons)
