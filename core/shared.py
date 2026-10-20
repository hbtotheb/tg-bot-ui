from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent.parent
ROOT = BOT_DIR.parent
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv(BOT_DIR / ".env")
load_dotenv(BOT_DIR / ".env.bot")

if os.getenv("USE_MOCK_DB", "").strip().lower() in ("1", "true", "yes") or not (ROOT / "database").is_dir():
    try:
        from core.mock_db import MockDatabase
    except ImportError:
        from bot.core.mock_db import MockDatabase
    db = MockDatabase()
else:
    try:
        from database import Database

        db = Database(os.getenv("DB_PATH", str(ROOT / "data" / "messages.db")))
    except ImportError:
        try:
            from core.mock_db import MockDatabase
        except ImportError:
            from bot.core.mock_db import MockDatabase
        db = MockDatabase()
