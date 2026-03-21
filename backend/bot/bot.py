import os
import logging
from datetime import datetime, timedelta

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL   = os.getenv("API_URL", "http://fastapi:8000")
ROOM_ID   = "room1"

slot_store = {}

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏢 *Coworking Bot*\n\n"
        "/status — current occupancy\n"
        "/schedule — today's bookings\n"
        "/book — reserve a slot\n",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_URL}/status", params={"room_id": ROOM_ID})
            data = r.json()
        status = data.get("status", "unknown")
        ts = data.get("timestamp", "")[:19].replace("T", " ")
        emoji = {"busy": "🔴", "free": "🟢"}.get(status, "⚪")
        await update.message.reply_text(f"{emoji} Room is *{status.upper()}*\nUpdated: {ts}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_URL}/bookings", params={"room_id": ROOM_ID, "date": today})
            bookings = r.json()
        if not bookings:
            await update.message.reply_text(f"📅 No bookings today ({today})")
            return
        lines = [f"📅 *Schedule for {today}*\n"]
        for b in bookings:
            start = b["start_time"][11:16]
            end = b["end_time"][11:16]
            lines.append(f"  {start}–{end}: {b['user_name']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_book(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    slot_store.clear()
    keyboard = []
    for i in range(4):
        s = start + timedelta(hours=i)
        e = s + timedelta(hours=1)
        slot_store[str(i)] = {"start": s.isoformat(), "end": e.isoformat()}
        keyboard.append([InlineKeyboardButton(
            f"📌 {s.strftime('%H:%M')}–{e.strftime('%H:%M')}",
            callback_data=str(i)
        )])
    await update.message.reply_text(
        "Select a 1-hour slot:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot = slot_store.get(query.data)
    if not slot:
        await query.edit_message_text("❌ Slot expired, use /book again.")
        return
    user = query.from_user
    try:
        async with httpx.AsyncClient() as client:
            auth = await client.post(f"{API_URL}/auth/token", json={"username": "admin", "password": "admin"})
            token = auth.json()["access_token"]
            r = await client.post(
                f"{API_URL}/booking",
                json={
                    "room_id": ROOM_ID,
                    "user_name": user.first_name or "Unknown",
                    "start_time": slot["start"],
                    "end_time": slot["end"],
                    "description": "Booked via Telegram"
                },
                headers={"Authorization": f"Bearer {token}"}
            )
        if r.status_code == 201:
            s = slot["start"][11:16]
            e = slot["end"][11:16]
            await query.edit_message_text(f"✅ Booked *{s}–{e}*!", parse_mode="Markdown")
        elif r.status_code == 409:
            await query.edit_message_text("❌ Already taken. Try /book again.")
        else:
            await query.edit_message_text(f"❌ Failed: {r.text}")
    except Exception as ex:
        await query.edit_message_text(f"❌ Error: {ex}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("book", cmd_book))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.run_polling()

if __name__ == "__main__":
    main()
