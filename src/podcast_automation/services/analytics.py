"""
YouTube Analytics pull service.

Fetches view/like/comment counts for uploaded Shorts via the YouTube Data API
and stores them in the local SQLite database.

Called by the separate `analytics.yml` GitHub Actions workflow that runs
24 h (or more) after the main pipeline.
"""
import re
from typing import Optional, Dict
from loguru import logger
from ..config import settings
from ..database import db_manager
from ..utils.retry import with_retry

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore


def _extract_video_id(youtube_url: str) -> Optional[str]:
    """Extract the raw video ID from a YouTube Shorts / watch URL."""
    patterns = [
        r"youtube\.com/shorts/([A-Za-z0-9_\-]{11})",
        r"youtube\.com/watch\?v=([A-Za-z0-9_\-]{11})",
        r"youtu\.be/([A-Za-z0-9_\-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, youtube_url)
        if m:
            return m.group(1)
    return None


@with_retry(max_attempts=3, base_delay=2.0)
def _fetch_stats(video_id: str) -> Optional[Dict]:
    """
    Call YouTube Data API v3 statistics endpoint.
    Returns dict with 'views', 'likes', 'comments' or None on failure.
    """
    if not settings.YOUTUBE_API_KEY:
        logger.warning("YOUTUBE_API_KEY not set — cannot fetch analytics.")
        return None

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "statistics",
        "id": video_id,
        "key": settings.YOUTUBE_API_KEY,
    }
    resp = _requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])
    if not items:
        logger.warning(f"No stats found for video_id={video_id}")
        return None
    stats = items[0].get("statistics", {})
    return {
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
    }


def run_analytics_update(delay_hours: int = settings.ANALYTICS_DELAY_HOURS):
    """
    Main entry point called by the analytics workflow.

    Fetches stats for all uploaded Shorts that haven't been measured yet
    (or whose stats are stale) and updates the database.
    """
    if not settings.YOUTUBE_API_KEY:
        logger.error(
            "❌ YOUTUBE_API_KEY is required for analytics. "
            "Set it as a GitHub Actions secret."
        )
        return

    pending = db_manager.get_shorts_pending_analytics(delay_hours=delay_hours)
    logger.info(f"Analytics update: {len(pending)} short(s) to process.")

    for short in pending:
        video_url = short.get("video_url", "")
        short_id = short.get("id")
        if not video_url or not short_id:
            continue

        video_id = _extract_video_id(video_url)
        if not video_id:
            logger.warning(f"Could not parse video_id from URL: {video_url}")
            continue

        try:
            stats = _fetch_stats(video_id)
        except Exception as e:
            logger.error(f"Stats fetch failed for {video_id}: {e}")
            continue

        if stats:
            db_manager.update_short_analytics(
                short_id=short_id,
                views=stats["views"],
                likes=stats["likes"],
                comments=stats["comments"],
            )
            logger.info(
                f"✅ {short.get('title', video_id)}: "
                f"{stats['views']:,} views, {stats['likes']:,} likes, "
                f"{stats['comments']:,} comments"
            )

    logger.info("Analytics update complete.")
