"""Telegram notification — ported from TOBOR (SDD §7)."""

import os

import httpx

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send Telegram message. Returns True on success, False on failure. Never raises."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            if response.status_code == 200:
                return True

            # Retry without parse_mode on 400 (might be formatting issue)
            if response.status_code == 400 and parse_mode != "":
                payload["parse_mode"] = ""
                response = await client.post(url, json=payload, timeout=30.0)
                return response.status_code == 200

            return False
    except Exception:
        return False
