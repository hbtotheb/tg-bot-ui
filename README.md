# Telegram Search Bot - Bot UI Module

This service runs the interactive Telegram search bot interface. It provides users with a fast search engine and a filtered listing browse menu.

---

## 🚀 Useful Commands

### Start the Bot
Run the bot client loop to listen and respond to Telegram chats:
```bash
python bot/bot.py
```

---

## ⚙️ Configuration (`bot/.env.bot`)

Copy `.env.bot.example` to `.env.bot` to set up credentials:
* `TELEGRAM_BOT_TOKEN`: The API token obtained from Telegram's `@BotFather`.

*Note: The bot also reads connection credentials for database access from the root `.env`. When running standalone without the backend `database` package (or when `USE_MOCK_DB=1`), it automatically falls back to `MockDatabase` seeded from `fixtures/mock_data.json`.*

---

## 💬 User Interface Commands

* `/start` — Opens the main help guide and feature modules (Recommendation Cards, Custom Inquiry, Ads).
* `/search <keyword>` — Standard FTS5 text search query.
* `/browse` — Interactive selection filters to browse listings by Service, City, District, and Price Range.
* `/recent` — Lists the latest parsed and indexed messages.
* `/filter` — Activates channel-specific search filters.
* `/stats` — Displays current indexes and message telemetry statistics.
* `/analytics` — Full BI dashboard displaying DAU, active user browsing durations, top search queries, and 7-day retention trends.

---

## 🧪 Standalone UI Mode (`MockDatabase`)

To run the bot UI standalone without the production database or backend packages:
```bash
pip install -r requirements.txt
cp .env.bot.example .env.bot
python bot.py
```
Run UI and mock database unit tests:
```bash
pytest tests -v
```
