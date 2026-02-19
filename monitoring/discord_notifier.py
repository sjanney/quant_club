"""
Discord notifier (webhook-based, free).

Set DISCORD_WEBHOOK_URL in environment to enable.
"""

import logging
from typing import Optional

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


def discord_enabled() -> bool:
    """Whether Discord notifications are enabled and configured."""
    return bool(settings.notifications.discord_enabled and settings.notifications.discord_webhook_url)


def send_discord_message(content: str) -> bool:
    """
    Send a message to Discord webhook.
    Returns True when sent, False if skipped/failed.
    """
    if not discord_enabled():
        return False

    url = settings.notifications.discord_webhook_url
    payload = {"content": content[:1900]}  # keep below Discord 2000 char cap
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code >= 400:
            logger.warning("Discord webhook failed: %s %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as e:
        logger.warning("Discord webhook exception: %s", e)
        return False
