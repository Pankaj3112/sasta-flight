import json
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import CHAT_ID
from bot.db import Database
from bot.scanner import scan_route
from bot.formatter import (
    format_daily_message,
    format_error_message,
    format_history_message,
)

logger = logging.getLogger(__name__)

# Global db reference, set in main.py
db: Database = None


def _is_authorized(update: Update) -> bool:
    return update.effective_chat.id == CHAT_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "✈️ SastaFlight - Daily Flight Price Scanner\n\n"
        "Commands:\n"
        "/add <from> <to> - Add a route (e.g. /add ATQ BOM)\n"
        "/remove <id> - Remove a route\n"
        "/routes - List active routes\n"
        "/check - Scan all routes now\n"
        "/time <HH:MM> - Set daily scan time (24h, IST)\n"
        "/history - 7-day price trend\n"
        "/pause - Pause daily updates\n"
        "/resume - Resume daily updates\n"
        "/help - Show this message"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await start_command(update, context)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /add <from> <to>\nExample: /add ATQ BOM")
        return

    from_code = context.args[0].upper()
    to_code = context.args[1].upper()

    if len(from_code) != 3 or len(to_code) != 3:
        await update.message.reply_text("Airport codes must be 3 letters (IATA codes).")
        return

    route_id = await db.add_route(from_code, to_code)
    await update.message.reply_text(
        f"✅ Route added: {from_code} → {to_code} (ID: {route_id})\n"
        "Use /check to run a scan now."
    )


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /remove <id>\nUse /routes to see route IDs.")
        return

    try:
        route_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Route ID must be a number.")
        return

    removed = await db.remove_route(route_id)
    if removed:
        await update.message.reply_text(f"✅ Route {route_id} removed.")
    else:
        await update.message.reply_text(f"❌ Route {route_id} not found.")


async def routes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes. Use /add to add one.")
        return

    lines = ["📋 Active Routes:\n"]
    for r in routes:
        lines.append(f"  {r['id']}. {r['from_airport']} → {r['to_airport']}")
    await update.message.reply_text("\n".join(lines))


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes. Use /add to add one.")
        return

    await update.message.reply_text("🔍 Scanning... this may take a moment.")

    for route in routes:
        await _scan_and_send(context, route)


async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not context.args or len(context.args) != 1:
        current = await db.get_config("notify_time")
        await update.message.reply_text(
            f"Current scan time: {current} IST\nUsage: /time <HH:MM>"
        )
        return

    time_str = context.args[0]
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await update.message.reply_text("Invalid format. Use HH:MM (e.g. 08:00, 14:30)")
        return

    await db.set_config("notify_time", time_str)

    # Reschedule - import here to avoid circular
    from bot.main import schedule_daily_job
    await schedule_daily_job(context.application)

    await update.message.reply_text(f"✅ Daily scan time set to {time_str} IST")


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    routes = await db.get_active_routes()
    if not routes:
        await update.message.reply_text("No active routes.")
        return

    for route in routes:
        history = await db.get_price_history(route["id"], days=7)
        msg = format_history_message(route["from_airport"], route["to_airport"], history)
        await update.message.reply_text(msg)


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await db.set_config("is_paused", "1")
    await update.message.reply_text("⏸ Daily updates paused. Use /resume to restart.")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await db.set_config("is_paused", "0")
    await update.message.reply_text("▶️ Daily updates resumed.")


async def _scan_and_send(context: ContextTypes.DEFAULT_TYPE, route: dict, is_retry: bool = False):
    """Scan a single route and send the result. Schedule retry on failure."""
    from_code = route["from_airport"]
    to_code = route["to_airport"]

    result = await scan_route(from_code, to_code)

    if result is None:
        if is_retry:
            msg = (
                f"❌ {from_code} → {to_code}\n"
                "Scan failed after retry. Will try again tomorrow.\n"
                "Run /check to try manually."
            )
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        else:
            msg = format_error_message(from_code, to_code)
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
            # Schedule retry in 4 hours
            context.job_queue.run_once(
                _retry_scan_job,
                when=4 * 60 * 60,
                data=route,
                name=f"retry_{route['id']}",
            )
        return

    # Get previous cheapest for trend
    history = await db.get_price_history(route["id"], days=1)
    prev_cheapest = history[0]["cheapest_price"] if history else None

    # Save to history
    today = datetime.now().strftime("%Y-%m-%d")
    await db.save_price_history(
        route_id=route["id"],
        scan_date=today,
        cheapest_travel_date=result.cheapest_travel_date,
        cheapest_price=result.cheapest_price,
        cheapest_airline=result.cheapest_airline,
        avg_price=result.avg_price,
        price_data=json.dumps(result.top_days),
    )

    msg = format_daily_message(result, prev_cheapest=prev_cheapest)
    await context.bot.send_message(chat_id=CHAT_ID, text=msg)


async def _retry_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Retry a failed scan (called by JobQueue)."""
    route = context.job.data
    await _scan_and_send(context, route, is_retry=True)


async def daily_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Daily scheduled job: scan all routes if not paused."""
    is_paused = await db.get_config("is_paused")
    if is_paused == "1":
        return

    routes = await db.get_active_routes()
    if not routes:
        return

    for route in routes:
        await _scan_and_send(context, route)
