from __future__ import annotations

import base64
import html
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.admin import is_admin
from core.i18n import t
from core.rate_limiter import rate_limiter
from core.shared import db
from ui.formatters import _lang, send_news


async def _render_analytics_text(days_overview: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    """Builds formatted HTML dashboard and keyboard for BI analytics."""
    if days_overview:
        overview = await db.get_retention_overview(days=7)
        lines = [
            "📈 <b>最近 7 天活跃与留存趋势 (7-Day Overview)</b>\n",
            "<blockquote>日期 | 访客(DAU) | 新增 | 总交互 | 人均停留",
            "──────────────────────────",
        ]
        for row in overview:
            lines.append(
                f"• <b>{row['date']}</b>: <b>{row['dau']}</b> 人 (新: {row['new_users']}) | {row['total_events']}次 | ⏱️ {row['avg_duration']}"
            )
        lines.append("</blockquote>\n💡 <i>数据每分钟实时统计更新</i>")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 查看今日实时明细", callback_data="feat:analytics_today")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="feat:start")],
        ])
        return "\n".join(lines), keyboard

    # Today's detailed dashboard
    summary = await db.get_daily_summary()
    active_users = await db.get_daily_active_users(limit=8)
    top_queries = await db.get_top_search_terms(limit=5)
    zero_queries = await db.get_zero_result_searches(limit=5)

    dau = summary["dau"]
    new_u = summary["new_users"]
    ret_u = summary["returning_users"]
    total_events = summary["total_events"]
    avg_actions = round(total_events / dau, 1) if dau else 0

    lines = [
        "📊 <b>机器人流量与数据分析 (BI Dashboard)</b>\n",
        "<blockquote>",
        f"👥 <b>今日访客 (DAU)：</b> <b>{dau}</b> 位独立用户\n"
        f"🆕 <b>新访客：</b> {new_u} 人 | 🔄 <b>老访客：</b> {ret_u} 人\n"
        f"⏱️ <b>人均浏览停留：</b> <b>{summary['formatted_avg_duration']}</b>\n"
        f"🕒 <b>总计浏览交互：</b> {summary['formatted_total_duration']}\n"
        f"⚡ <b>总交互事件：</b> {total_events} 次 (人均 {avg_actions} 次)\n"
        f"🔍 <b>搜索请求：</b> {summary['searches_count']} 次\n"
        f"🏷️ <b>筛选与翻页：</b> {summary['browse_actions_count']} 次\n"
        f"💾 <b>累计注册用户：</b> {summary['total_registered_users']:,} 人",
        "</blockquote>\n",
    ]

    # User breakdown
    if active_users:
        lines.append("👤 <b>今日访客明细 (今日最近活跃用户)：</b>")
        lines.append("<blockquote>")
        for u in active_users:
            uname = f"@{u['username']}" if u["username"] else html.escape(u["first_name"] or str(u["user_id"]))
            tag = " 🆕" if u["is_new"] else ""
            lines.append(
                f"• <b>{uname}</b>{tag} — ⏱️ <b>{u['formatted_duration']}</b> ({u['total_actions']}次交互, {u['last_seen_str']}活跃)"
            )
        lines.append("</blockquote>\n")
    else:
        lines.append("👤 <b>今日访客明细：</b>\n<blockquote>今日暂无交互记录</blockquote>\n")

    # Top search terms
    if top_queries:
        lines.append("🔥 <b>热门搜索关键词：</b>")
        lines.append("<blockquote>")
        for q in top_queries:
            lines.append(f"• <code>{html.escape(q['query'])}</code> — {q['count']} 次 (平均 {q['avg_results']} 条结果)")
        lines.append("</blockquote>\n")

    # Zero results terms (Opportunity gap)
    if zero_queries:
        lines.append("❓ <b>无结果搜索 (用户需求缺口)：</b>")
        lines.append("<blockquote>")
        for z in zero_queries:
            lines.append(f"• <code>{html.escape(z['query'])}</code> — {z['count']} 次无结果")
        lines.append("</blockquote>\n")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 刷新数据", callback_data="feat:analytics_today"),
            InlineKeyboardButton("📅 7天留存趋势", callback_data="feat:analytics_7d"),
        ],
        [InlineKeyboardButton("🏠 返回主菜单", callback_data="feat:start")],
    ])

    return "\n".join(lines), keyboard


logger = logging.getLogger(__name__)

HOMEPAGE_NUM_EMOJIS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
HOMEPAGE_DIVIDER = "────────────────────────"


def _make_search_link(clean_bot: str, kw: str) -> str:
    """Generates Telegram deep link to directly trigger search for a keyword."""
    b64 = base64.urlsafe_b64encode(kw.encode("utf-8")).decode("ascii").rstrip("=")
    return f"https://t.me/{clean_bot}?start=kw_b64_{b64}"


def _format_homepage_teacher_item(idx: int, teacher: dict[str, Any], clean_bot: str) -> str:
    num_emoji = HOMEPAGE_NUM_EMOJIS[idx] if idx < len(HOMEPAGE_NUM_EMOJIS) else f"{idx + 1}."
    name = html.escape(teacher.get("name") or teacher.get("canonical_name") or "精选老师")
    rating = teacher.get("rating") or 0.0

    tid = teacher.get("id") or 0
    detail_url = f"https://t.me/{clean_bot}?start=tc_{tid}_0"

    loc = teacher.get("district") or teacher.get("city") or teacher.get("canonical_city") or ""
    loc_clean = html.escape(loc) if loc else ""

    price = teacher.get("price_p") or teacher.get("price")
    price_str = ""
    if price and float(price) > 0:
        p_val = float(price)
        p_fmt = str(int(p_val)) if p_val.is_integer() else f"{p_val:.1f}"
        price_str = f"¥{p_fmt}"

    info_parts = [f"⭐ {rating:.1f}"]
    if loc_clean:
        info_parts.append(loc_clean)
    if price_str:
        info_parts.append(price_str)
    info_str = " · ".join(info_parts)

    raw_post_link = teacher.get("teacher_post_link")
    post_link = raw_post_link.strip() if raw_post_link and isinstance(raw_post_link, str) else None

    # Name itself is the primary clickable link
    title_parts = [
        f'{num_emoji} 💃 <a href="{html.escape(detail_url)}"><b>{name}</b></a> ({info_str})'
    ]
    if post_link and post_link.startswith(("http://", "https://", "tg://")):
        title_parts.append(f'<a href="{html.escape(post_link)}">[介绍 ↗]</a>')

    return " ".join(title_parts)


async def _get_suggested_keywords() -> tuple[list[str], list[str]]:
    """Returns (top_districts, top_tags) from the database with graceful defaults."""
    default_districts = ["静安", "徐汇", "浦东", "普陀", "闵行", "长宁"]
    default_tags = ["御姐", "甜妹", "嫩妹", "长腿", "女友感", "服务好"]
    try:
        async with db._read() as conn:
            cursor = await conn.execute(
                """
                SELECT district, COUNT(*) as cnt
                FROM teachers
                WHERE district IS NOT NULL AND district != ''
                GROUP BY district
                ORDER BY cnt DESC
                LIMIT 6
                """
            )
            rows = await cursor.fetchall()
            districts = [r["district"] for r in rows if r["district"]] or default_districts

            cursor = await conn.execute(
                """
                SELECT tags
                FROM teachers
                WHERE tags IS NOT NULL AND tags != ''
                LIMIT 100
                """
            )
            rows = await cursor.fetchall()
            c: Counter[str] = Counter()
            for r in rows:
                for t in str(r["tags"]).replace("，", ",").split(","):
                    clean = t.strip()
                    if clean and len(clean) <= 6:
                        c[clean] += 1
            tags = [tag for tag, _ in c.most_common(6)] or default_tags
            return districts, tags
    except Exception as e:
        logger.debug("Failed to fetch suggested keywords from db: %s", e)
        return default_districts, default_tags


async def render_homepage_text(
    lang: str = "zh",
    bot_username: str | None = None,
    popular_teachers: list[dict[str, Any]] | None = None,
    newest_teachers: list[dict[str, Any]] | None = None,
    teachers: list[dict[str, Any]] | None = None,
    suggested_districts: list[str] | None = None,
    suggested_tags: list[str] | None = None,
) -> str:
    """Builds the bot homepage message including most popular teachers (top 5), newest teachers (top 5), and suggested search keywords."""
    clean_bot = (bot_username or "").strip().lstrip("@")
    if not clean_bot:
        clean_bot = os.getenv("BOT_USERNAME", "tg_search_bot").strip().lstrip("@")

    if popular_teachers is None and teachers is not None:
        popular_teachers = teachers

    if popular_teachers is None:
        try:
            popular_teachers = await db.search_teachers(status="active", sort_by="rank", limit=5)
        except Exception as e:
            logger.debug("Failed to query popular teachers for homepage: %s", e)
            popular_teachers = []

    if newest_teachers is None:
        try:
            newest_teachers = await db.search_teachers(status="active", sort_by="recent", limit=5)
        except Exception as e:
            logger.debug("Failed to query newest teachers for homepage: %s", e)
            newest_teachers = []

    if suggested_districts is None or suggested_tags is None:
        db_dists, db_tags = await _get_suggested_keywords()
        if suggested_districts is None:
            suggested_districts = db_dists
        if suggested_tags is None:
            suggested_tags = db_tags

    lines = [
        "✨ <b>全国修车小龙虾 · 严选评测指南</b>\n",
        "<blockquote>🦞 <b>AI 智能整理真实报告 · 轻松选人不踩坑</b></blockquote>\n",
    ]

    # 1. Most Popular Teachers (Top 5)
    lines.append("🔥 <b>今日高分精选 · 最受喜爱老师 (Top 5)：</b>")
    lines.append(HOMEPAGE_DIVIDER)
    if popular_teachers:
        pop_items = [_format_homepage_teacher_item(i, t_item, clean_bot) for i, t_item in enumerate(popular_teachers[:5])]
        lines.append("\n".join(pop_items))
    else:
        lines.append("<blockquote>暂无已收录的高分老师数据</blockquote>")
    lines.append(HOMEPAGE_DIVIDER)
    lines.append("")

    # 2. Newest Teachers (Top 5)
    lines.append("🆕 <b>新晋入驻 · 最新收录老师 (Top 5)：</b>")
    lines.append(HOMEPAGE_DIVIDER)
    if newest_teachers:
        new_items = [_format_homepage_teacher_item(i, t_item, clean_bot) for i, t_item in enumerate(newest_teachers[:5])]
        lines.append("\n".join(new_items))
    else:
        lines.append("<blockquote>暂无最新收录的老师数据</blockquote>")
    lines.append(HOMEPAGE_DIVIDER)
    lines.append("")

    # 3. Suggested Search Keywords (deep links to search results directly)
    dist_links = " · ".join(
        f'<a href="{_make_search_link(clean_bot, d)}">#{html.escape(d)}</a>'
        for d in suggested_districts
    )
    tag_links = " · ".join(
        f'<a href="{_make_search_link(clean_bot, t)}">#{html.escape(t)}</a>'
        for t in suggested_tags
    )
    lines.append(
        "🔍 <b>推荐搜索（点击直接跳转搜索结果）：</b>\n"
        "<blockquote>"
        f"🏙️ <b>热门商圈：</b> {dist_links}\n"
        f"🏷️ <b>风格特色：</b> {tag_links}"
        "</blockquote>\n"
    )

    lines.append("💡 <i>点击老师名字直接查看详情档案，点击标签直达搜索结果 👇</i>")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    return text


def get_homepage_markup(lang: str = "zh", user_is_admin: bool = False) -> InlineKeyboardMarkup:
    """Builds inline keyboard markup for the bot homepage.

    City selection, subscription, and mode selection buttons are hidden for now.
    """
    buttons = [
        [InlineKeyboardButton("💃 推荐老师 (滑动卡片)", callback_data="tc:swipe:0")],
        [InlineKeyboardButton("📋 老师名录 (列表速览)", callback_data="tl:page:0")],
        [InlineKeyboardButton("🤖 AI对话", callback_data="inq:start")],
        [InlineKeyboardButton(t("btn_ads", lang), callback_data="feat:ads")],
    ]
    return InlineKeyboardMarkup(buttons)


async def send_homepage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Renders and sends or edits the bot homepage message."""
    user = update.effective_user
    lang = _lang(update)
    user_is_admin = is_admin(user.id if user else None)
    markup = get_homepage_markup(lang=lang, user_is_admin=user_is_admin)

    raw_bot_user = (
        getattr(context.bot, "username", None)
        if context and getattr(context, "bot", None)
        else None
    )
    bot_username = raw_bot_user if isinstance(raw_bot_user, str) and raw_bot_user else None
    text = await render_homepage_text(lang=lang, bot_username=bot_username)

    if update.callback_query:
        msg = update.callback_query.message
        if msg and msg.photo:
            try:
                await msg.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        else:
            await update.callback_query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=markup,
            disable_web_page_preview=True,
        )


async def on_feature_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and rate_limiter.is_callback_rate_limited(user.id, user.username):
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        return
    await update.callback_query.answer()
    lang = _lang(update)
    data = update.callback_query.data
    feat = data.split(":")[1]

    if feat == "start":
        await send_homepage(update, context)
        return

    if feat in ("analytics_today", "analytics_7d"):
        if not is_admin(user.id if user else None):
            try:
                await update.callback_query.answer("⛔ 权限不足：此管理面板仅限管理员访问。", show_alert=True)
            except Exception:
                pass
            return

        if feat == "analytics_today":
            text, markup = await _render_analytics_text(days_overview=False)
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
            return

        if feat == "analytics_7d":
            text, markup = await _render_analytics_text(days_overview=True)
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
            return

    text = ""
    if feat == "ads":
        text = t("ads_placeholder", lang)
    elif feat == "cities":
        text = t("cities_placeholder", lang)
    elif feat == "sub":
        text = t("subscribe_placeholder", lang)
    elif feat == "mode":
        text = t("mode_placeholder", lang)

    back_button = [[InlineKeyboardButton(t("btn_back", lang), callback_data="feat:start")]]
    await update.callback_query.edit_message_text(
        text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(back_button)
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    total_messages = await db.count()
    user = update.effective_user
    lang = _lang(update)

    if not is_admin(user.id if user else None):
        # Public statistics for regular users
        if update.message:
            await update.message.reply_text(t("stats", lang, total=total_messages), parse_mode="HTML")
        return

    # Admin view with quick operational metrics and analytics button
    summary = await db.get_daily_summary()
    text = (
        f"📊 <b>数据库与运营统计 (管理员视图)</b>\n\n"
        f"<blockquote>"
        f"💾 <b>索引消息总量：</b> <b>{total_messages:,}</b> 条\n"
        f"👥 <b>今日访客 (DAU)：</b> <b>{summary['dau']}</b> 人\n"
        f"⏱️ <b>人均停留时长：</b> <b>{summary['formatted_avg_duration']}</b>\n"
        f"⚡ <b>今日交互总数：</b> <b>{summary['total_events']}</b> 次"
        f"</blockquote>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 查看完整 BI 运营分析", callback_data="feat:analytics_today")],
        [InlineKeyboardButton("🏠 返回主菜单", callback_data="feat:start")],
    ])
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def cmd_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Direct command to view BI analytics dashboard (Admin only)."""
    user = update.effective_user
    if not is_admin(user.id if user else None):
        if update.message:
            await update.message.reply_text(
                "⛔ <b>权限不足</b>\n<blockquote>此分析统计面板仅对管理员开放。</blockquote>",
                parse_mode="HTML",
            )
        return

    text, markup = await _render_analytics_text(days_overview=False)
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(update)
    chat_id = update.effective_chat.id
    user = update.effective_user
    if user:
        await db.register_user(
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language=user.language_code,
        )
    await send_news(context.bot, chat_id, lang)
