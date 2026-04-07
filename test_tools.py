import os
import json
from datetime import datetime
import pytz
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TIMEZONE = os.getenv("TIMEZONE", "America/Mexico_City")
tz = pytz.timezone(DEFAULT_TIMEZONE)

def get_current_time() -> str:
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")

print(f"Current Time Tool Output: {get_current_time()}")

# Mock data for testing parse_datetime if needed
def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M")
        except Exception:
            return None

test_date = "2026-04-10 15:00"
parsed = parse_datetime(test_date)
print(f"Parsing '{test_date}': {parsed}")
if parsed:
    localized = tz.localize(parsed)
    print(f"Localized: {localized}")
