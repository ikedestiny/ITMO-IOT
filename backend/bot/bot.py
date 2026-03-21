import os
import asyncio
import json
import logging
from datetime import datetime, timedelta

import httpx
import aiomqtt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
API_URL     = os.getenv("API_URL", "http://fastapi:8000")
MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT   = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER   = os.getenv("MQTT_USER", "server")
MQTT_PASS   = os.getenv("MQTT_PASS", "serverpass")

ROOM_ID = "room1"  # default room

# ─── /start ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏢 *Coworking Bot*\n\n"
        "Commands:\n"
        "/status — current occupancy\n"
        "/schedule — today's bookings\n"
        "/book — reserve a slot\n"
        "/help — show this message",
        parse_mode="Markdown"
    )

# ─── /status ──────────────────────────────────────────────────────────────────
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_URL}/status", params={"room_id": ROOM_ID})
            data = r.json()
        status = data.get("status", "unknown")
        ts     = data.get("timestamp", "")[:19].replace("T", " ")

        emoji = {"busy": "🔴", "free": "🟢"}.get(status, "⚪")
        text  = f"{emoji} Room is *{status.upper()}*\nUpdated: {ts}"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Could not fetch status: {e}")

# ─── /schedule ────────────────────────────────────────────────────────────────
async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_URL}/bookings",
                                 params={"room_id": ROOM_ID, "date": today})
            bookings = r.json()

        if not bookings:
            await update.message.reply_text(f"📅 No bookings today ({today})")
            return

        lines = [f"📅 *Schedule for {today}*\n"]
        for b in bookings:
            start = b["start_time"][11:16]
            end   = b["end_time"][11:16]
            lines.append(f"  {start}–{end}: {b['user_name']} — {b['description'] or '—'}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ─── /book ────────────────────────────────────────────────────────────────────
async def cmd_book(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Offer quick booking slots as inline buttons
    now   = datetime.now()
    slots = []
    # Generate next 4 available 1-hour slots
    start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for i in range(4):
        s = start + timedelta(hours=i)
        e = s + timedelta(hours=1)
        slots.append((s.strftime("%H:%M"), e.strftime("%H:%M"),
                      s.isoformat(), e.isoformat()))

    keyboard = [
        [InlineKeyboardButton(
            f"📌 {s}–{e}",
            callback_data=json.dumps({"action": "book", "start": si, "end": ei})
        )]
        for s, e, si, ei in slots
    ]
    await update.message.reply_text(
        "Select a 1-hour slot to book:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─── Inline button handler ────────────────────────────────────────────────────
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    if data.get("action") != "book":
        return

    user = query.from_user
    start = data["start"]
    end   = data["end"]

    # Get auth token (use hardcoded demo token — replace with real auth)
    try:
        async with httpx.AsyncClient() as client:
            auth = await client.post(f"{API_URL}/auth/token",
                                     json={"username": "admin", "password": "admin"})
            token = auth.json()["access_token"]

            r = await client.post(
                f"{API_URL}/booking",
                json={
                    "room_id": ROOM_ID,
                    "user_name": user.first_name or user.username or "Unknown",
                    "start_time": start,
                    "end_time": end,
                    "description": "Booked via Telegram"
                },
                headers={"Authorization": f"Bearer {token}"}
            )

        if r.status_code == 201:
            start_str = start[11:16]
            end_str   = end[11:16]
            await query.edit_message_text(
                f"✅ Booked! *{start_str}–{end_str}*\n"
                f"Room: {ROOM_ID} | By: {user.first_name}",
                parse_mode="Markdown"
            )
        elif r.status_code == 409:
            await query.edit_message_text("❌ That slot is already taken. Try /book again.")
        else:
            await query.edit_message_text(f"❌ Booking failed: {r.text}")
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {e}")

# ─── /help ────────────────────────────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("book",     cmd_book))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CallbackQueryHandler(on_button))

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
