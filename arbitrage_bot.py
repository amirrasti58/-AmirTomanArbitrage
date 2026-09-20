"""
AmirTomanArbitrage
مرحله ۳ و ۴: تست اتصال امن به تلگرام
"""

import os
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR | توکن یا چت آیدی تلگرام تنظیم نشده (Secret ها رو چک کن)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=15,
        )
        response.raise_for_status()

        print("SUCCESS | پیام با موفقیت به تلگرام ارسال شد")
        return True

    except Exception as e:
        print(f"ERROR | خطا در ارسال پیام تلگرام: {e}")
        return False


if __name__ == "__main__":
    print("AmirTomanArbitrage is running successfully!")

    send_telegram_message(
        "✅ ربات AmirTomanArbitrage با موفقیت به تلگرام وصل شد."
    )
