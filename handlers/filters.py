from __future__ import annotations

import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.i18n import t
from core.shared import db
from ui.formatters import _lang


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang  = _lang(update)
    chats = await db.get_chats(limit=20)
    if not chats:
        await update.message.reply_text(t("no_channels", lang), parse_mode="HTML")
        return

    current = context.user_data.get("chat_filter")

    buttons = []
    for c in chats:
        label = (c["chat_title"] or f"id:{c['chat_id']}")[:28]
        if current and current == c["chat_id"]:
            label = f"✓ {label}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"cf:{c['chat_id']}")])

    all_label = f"✓ {t('all_channels', lang)}" if not current else t("all_channels", lang)
    buttons.append([InlineKeyboardButton(all_label, callback_data="cf:0")])

    if current:
        match      = next((c for c in chats if c["chat_id"] == current), None)
        fname      = match["chat_title"] if match else f"id:{current}"
        status     = t("filter_active", lang, name=escape(fname))
    else:
        status = t("filter_none", lang)

    await update.message.reply_text(
        status + t("filter_prompt", lang),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


from core.rate_limiter import rate_limiter


async def on_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and rate_limiter.is_callback_rate_limited(user.id, user.username):
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        return

    await update.callback_query.answer()
    lang    = _lang(update)
    chat_id = int(update.callback_query.data.split(":")[1])

    if chat_id == 0:
        context.user_data.pop("chat_filter", None)
        await update.callback_query.edit_message_text(t("filter_cleared", lang), parse_mode="HTML")
    else:
        context.user_data["chat_filter"] = chat_id
        await update.callback_query.edit_message_text(t("filter_set", lang), parse_mode="HTML")
