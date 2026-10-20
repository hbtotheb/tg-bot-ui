from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(Path(__file__).parent / ".env.bot")

from telegram import Bot
from telegram.error import BadRequest, Forbidden, RetryAfter
from core.i18n import get_lang, t
from database import Database
from ui.formatters import send_news


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BROADCAST_DELAY_SECONDS = float(os.getenv("BROADCAST_DELAY_SECONDS", "0.08"))  # ~12-15 msgs/sec


async def main(text_zh: str | None = None, text_en: str | None = None) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set.")
        return

    db = Database(os.getenv("DB_PATH", str(ROOT / "data" / "messages.db")))
    await db.init()

    users = await db.get_bot_users()
    if not users:
        logger.info("No registered users found in the database.")
        await db.close()
        return

    async with Bot(token) as bot:
        logger.info("Starting broadcast to %d users (throttle: %.2fs/msg)...", len(users), BROADCAST_DELAY_SECONDS)

        sent_count = 0
        blocked_count = 0
        failed_count = 0

        for u in users:
            chat_id = u["chat_id"]
            lang = get_lang(u.get("language"))
            
            # Send with retry on Telegram FloodWait/RetryAfter
            for attempt in range(2):
                try:
                    if text_zh or text_en:
                        msg_text = text_zh if lang == "zh" else text_en
                        if not msg_text:
                            msg_text = text_zh or text_en
                        await bot.send_message(
                            chat_id=chat_id,
                            text=msg_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    else:
                        await send_news(bot, chat_id, lang)
                    sent_count += 1
                    break
                except RetryAfter as e:
                    logger.warning("Rate limit (FloodWait) hit: sleeping for %d seconds...", e.retry_after)
                    await asyncio.sleep(e.retry_after + 0.5)
                except Forbidden:
                    logger.info("User %s blocked the bot or account deleted. Skipping.", chat_id)
                    blocked_count += 1
                    break
                except BadRequest as e:
                    logger.warning("BadRequest sending to %s: %s", chat_id, e)
                    failed_count += 1
                    break
                except Exception as e:
                    logger.warning("Failed to send message to chat_id %s: %s", chat_id, e)
                    failed_count += 1
                    break

            await asyncio.sleep(BROADCAST_DELAY_SECONDS)

        logger.info(
            "Broadcast complete. Sent: %d, Blocked: %d, Failed: %d (Total: %d)",
            sent_count,
            blocked_count,
            failed_count,
            len(users),
        )
    await db.close()
    await asyncio.sleep(0.1)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description="Broadcast news to all registered bot users.")
    parser.add_argument("--zh", type=str, help="Custom Chinese news message (HTML supported)")
    parser.add_argument("--en", type=str, help="Custom English news message (HTML supported)")
    args = parser.parse_args()
    asyncio.run(main(text_zh=args.zh, text_en=args.en))
