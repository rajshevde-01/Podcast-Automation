"""
Multi-platform notification service.

Supports: Discord, Slack, Telegram.
All channels are optional — only fires when the corresponding secret is set.
"""
import os
import requests
from typing import Optional
from loguru import logger
from ..config import settings


class NotificationService:
    # ------------------------------------------------------------------
    # Discord
    # ------------------------------------------------------------------

    def send_discord(
        self,
        title: str,
        url: str,
        thumbnail_path: Optional[str] = None,
        views: Optional[int] = None,
    ):
        if not settings.DISCORD_WEBHOOK_URL:
            return
        body = f"🚀 **New Podcast Short!**\n*{title}*\nWatch: {url}"
        if views is not None:
            body += f"\n📊 Views (24 h): {views:,}"
        try:
            if thumbnail_path and os.path.exists(thumbnail_path):
                with open(thumbnail_path, "rb") as fh:
                    requests.post(
                        settings.DISCORD_WEBHOOK_URL,
                        data={"content": body},
                        files={"file": ("thumbnail.jpg", fh, "image/jpeg")},
                        timeout=10,
                    )
            else:
                requests.post(
                    settings.DISCORD_WEBHOOK_URL,
                    json={"content": body},
                    timeout=10,
                )
            logger.info("Discord notification sent.")
        except Exception as e:
            logger.error(f"Discord notification failed: {e}")

    # ------------------------------------------------------------------
    # Slack
    # ------------------------------------------------------------------

    def send_slack(
        self,
        title: str,
        url: str,
        views: Optional[int] = None,
    ):
        if not settings.SLACK_WEBHOOK_URL:
            return
        text = f":rocket: *New Podcast Short!*\n_{title}_\nWatch: {url}"
        if views is not None:
            text += f"\n:bar_chart: Views (24 h): {views:,}"
        try:
            requests.post(
                settings.SLACK_WEBHOOK_URL,
                json={"text": text},
                timeout=10,
            )
            logger.info("Slack notification sent.")
        except Exception as e:
            logger.error(f"Slack notification failed: {e}")

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    def send_telegram(
        self,
        title: str,
        url: str,
        thumbnail_path: Optional[str] = None,
        views: Optional[int] = None,
    ):
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return
        text = f"🚀 *New Podcast Short!*\n_{title}_\n[Watch on YouTube]({url})"
        if views is not None:
            text += f"\n📊 Views (24 h): {views:,}"
        base_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
        try:
            if thumbnail_path and os.path.exists(thumbnail_path):
                with open(thumbnail_path, "rb") as fh:
                    requests.post(
                        f"{base_url}/sendPhoto",
                        data={
                            "chat_id": settings.TELEGRAM_CHAT_ID,
                            "caption": text,
                            "parse_mode": "Markdown",
                        },
                        files={"photo": ("thumbnail.jpg", fh, "image/jpeg")},
                        timeout=15,
                    )
            else:
                requests.post(
                    f"{base_url}/sendMessage",
                    json={
                        "chat_id": settings.TELEGRAM_CHAT_ID,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": False,
                    },
                    timeout=10,
                )
            logger.info("Telegram notification sent.")
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")

    # ------------------------------------------------------------------
    # Broadcast helper — fires all configured channels
    # ------------------------------------------------------------------

    def broadcast(
        self,
        title: str,
        url: str,
        thumbnail_path: Optional[str] = None,
        views: Optional[int] = None,
    ):
        self.send_discord(title, url, thumbnail_path, views)
        self.send_slack(title, url, views)
        self.send_telegram(title, url, thumbnail_path, views)


notification_service = NotificationService()
