from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.i18n import t
from ui.formatters import _lang

logger = logging.getLogger("BotErrorHandler")


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global handler for catching unhandled exceptions across all bot commands and inline buttons.
    
    Provides immediate, user-friendly client-side alerts (modal popups for buttons, text replies for messages)
    when server or database errors occur.
    """
    logger.error("Unhandled exception processing update (%s): %s", update, context.error, exc_info=context.error)

    if not isinstance(update, Update):
        return

    lang = _lang(update) if hasattr(update, "effective_user") else "zh"

    # 1. Client-side notification for inline button clicks (CallbackQuery)
    if update.callback_query:
        try:
            alert_text = t("err_server_busy_alert", lang)
            # show_alert=True renders an instant native modal popup window on the Telegram client
            await update.callback_query.answer(text=alert_text, show_alert=True)
        except Exception as e:
            logger.debug("Failed to deliver callback query error alert: %s", e)

    # 2. Client-side notification for text messages and slash commands
    elif update.effective_message:
        try:
            error_msg = t("err_server_busy_msg", lang)
            await update.effective_message.reply_text(error_msg, parse_mode="HTML")
        except Exception as e:
            logger.debug("Failed to deliver message error notification: %s", e)
