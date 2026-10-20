from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path


def _sigint_handler(signum, frame):
    sys.stdout.write("\n[Info] Bot process stopped cleanly.\n")
    sys.stdout.flush()
    os._exit(0)


try:
    signal.signal(signal.SIGINT, _sigint_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sigint_handler)
except Exception:
    pass


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
load_dotenv(Path(__file__).parent / ".env.bot")
load_dotenv(ROOT / "extractor" / "review_llm_extractor" / ".env.review_extractor")
load_dotenv(ROOT / "extractor" / ".env.extractor")

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    TypeHandler,
    filters,
)

from handlers.browse import cmd_browse, on_browse_callback
from handlers.features import cmd_analytics, cmd_news, cmd_stats, on_feature_callback
from handlers.filters import cmd_filter, on_filter_callback
from handlers.teachers import (
    cmd_teachers,
    cmd_teachers_list,
    on_teacher_card_callback,
    on_teacher_list_callback,
)
from inquiry.handlers import on_inquiry_callback, on_inquiry_location
from handlers.search import (
    cmd_recent,
    cmd_search,
    cmd_start,
    on_page_callback,
    on_text,
)
from core.error_handler import global_error_handler
from core.shared import db


from logging.handlers import RotatingFileHandler

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
bot_log_file = LOG_DIR / "bot.log"

log_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    file_handler = RotatingFileHandler(
        str(bot_log_file),
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    log_handlers.append(file_handler)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    await db.init()
    logger.info("Database initialized at %s", db.path)
    try:
        me = await application.bot.get_me()
        logger.info("Bot authenticated as @%s", me.username)
    except Exception as e:
        logger.debug("Note: Could not get bot identity during post_init: %s", e)


async def post_shutdown(application: Application) -> None:
    await db.close()
    logger.info("Database closed cleanly.")


async def track_user_interaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global telemetry middleware to track user activity, session timestamps, and queries."""
    user = update.effective_user
    if not user or user.is_bot:
        return

    chat_id = update.effective_chat.id if update.effective_chat else user.id

    # 1. Update user profile and last active timestamp
    try:
        await db.register_user(
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language=user.language_code,
        )
    except Exception as e:
        logger.debug("Telemetry user registration note: %s", e)

    # 2. Record telemetry interaction
    try:
        if update.message and update.message.text:
            text = update.message.text.strip()
            if text.startswith("/"):
                cmd = text.split()[0].lower()
                await db.record_telemetry("command", user_id=user.id, details={"command": cmd})
            else:
                await db.record_telemetry("query_input", user_id=user.id, query=text[:100])
        elif update.callback_query and update.callback_query.data:
            data = update.callback_query.data
            prefix = data.split(":")[0] if ":" in data else "cb"
            action = data.split(":")[1] if ":" in data else ""
            await db.record_telemetry(
                f"cb_{prefix}",
                user_id=user.id,
                details={"action": action, "data": data[:60]},
            )
    except Exception as e:
        logger.debug("Telemetry event record note: %s", e)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set — copy bot/.env.bot.example to bot/.env.bot")

    persistence_path = Path(os.getenv("BOT_PERSISTENCE_PATH", str(ROOT / "data" / "bot_state.pickle")))
    if persistence_path.parent:
        persistence_path.parent.mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(filepath=str(persistence_path))

    app = (
        Application.builder()
        .token(token)
        .persistence(persistence)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Global Client-side Error Handler
    app.add_error_handler(global_error_handler)

    # Global Telemetry Tracker (Runs before other handlers on all updates)
    app.add_handler(TypeHandler(Update, track_user_interaction), group=-1)

    # Command Handlers
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["teacher", "teachers", "card"], cmd_teachers))
    app.add_handler(CommandHandler(["list", "teachers_list"], cmd_teachers_list))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("filter", cmd_filter))
    app.add_handler(CommandHandler("browse", cmd_browse))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("analytics", cmd_analytics))
    app.add_handler(CommandHandler("news", cmd_news))

    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(on_teacher_card_callback, pattern=r"^tc:"))
    app.add_handler(CallbackQueryHandler(on_teacher_list_callback, pattern=r"^tl:"))
    app.add_handler(CallbackQueryHandler(on_inquiry_callback, pattern=r"^inq:"))
    app.add_handler(CallbackQueryHandler(on_feature_callback, pattern=r"^feat:"))
    app.add_handler(CallbackQueryHandler(on_filter_callback, pattern=r"^cf:"))
    app.add_handler(CallbackQueryHandler(on_browse_callback, pattern=r"^br:"))
    app.add_handler(CallbackQueryHandler(on_page_callback, pattern=r"^sp:(\d+|noop)$"))

    # Location Handler (For native map pin & geo coordinates in inquiry wizard)
    app.add_handler(MessageHandler(filters.LOCATION, on_inquiry_location))

    # Default Message Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))


    logger.info("Bot started")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)
    except (KeyboardInterrupt, SystemExit):
        sys.stdout.write("\n[Info] Bot process stopped cleanly.\n")
        sys.stdout.flush()
        os._exit(0)
    except Exception as e:
        if "anyio" not in str(e).lower() and "cancel" not in str(e).lower():
            logger.error("Bot exited with error: %s", e)


def _quiet_excepthook(exctype, value, traceback):
    if issubclass(exctype, (KeyboardInterrupt, SystemExit)):
        sys.stdout.write("\n[Info] Bot process stopped cleanly.\n")
        sys.stdout.flush()
        os._exit(0)
    sys.__excepthook__(exctype, value, traceback)


if __name__ == "__main__":
    sys.excepthook = _quiet_excepthook
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        sys.stdout.write("\n[Info] Bot process stopped cleanly.\n")
        sys.stdout.flush()
        os._exit(0)
