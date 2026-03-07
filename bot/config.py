import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
DAYS_TO_SCAN = int(os.getenv("DAYS_TO_SCAN", "30"))
TOP_CHEAPEST = int(os.getenv("TOP_CHEAPEST", "5"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
DB_PATH = os.getenv("DB_PATH", "data/flights.db")
