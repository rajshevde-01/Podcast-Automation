"""
Copyright Safety Checker Service.

Uses the YouTube Data API to evaluate whether a video is safe to clip:
  - Checks the video license type (creativeCommon vs youtube standard)
  - Checks the licensedContent flag (Content ID tracking)
  - Cross-references with channel-level copyright_risk rating
"""

import requests as http_requests
from typing import Optional
from loguru import logger
from ..config import settings
from ..models import CopyrightCheckResult

class CopyrightCheckerService:
    def __init__(self, api_key: str = settings.YOUTUBE_API_KEY):
        self.api_key = api_key

    def check_video(self, video_id: str, channel_risk: str = "medium") -> CopyrightCheckResult:
        """
        Performs a multi-layer copyright safety check on a video.
        
        Layers:
        1. YouTube Data API: license type + licensedContent flag
        2. Channel-level risk rating from our curated list
        3. Combined scoring → is_safe verdict
        """
        result = CopyrightCheckResult(
            video_id=video_id,
            is_safe=False,
            risk_level="high",
            reason="Not yet checked"
        )

        # Layer 1: YouTube Data API check
        if self.api_key:
            api_result = self._check_via_api(video_id)
            if api_result:
                result.license_type = api_result.get("license", "youtube")
                result.is_licensed_content = api_result.get("licensedContent", False)
        else:
            logger.warning("No YouTube API key set — skipping API-based copyright check.")

        # Layer 2: Combine with channel risk
        # Creative Commons = always safe
        if result.license_type == "creativeCommon":
            result.is_safe = True
            result.risk_level = "low"
            result.reason = "Video is Creative Commons licensed — safe to clip."
            return result

        # Standard license + NOT Content ID tracked + low channel risk = safe
        if not result.is_licensed_content and channel_risk == "low":
            result.is_safe = True
            result.risk_level = "low"
            result.reason = "No Content ID + low-risk channel — safe to clip with attribution."
            return result

        # Standard license + NOT Content ID tracked + medium channel risk = cautious OK
        if not result.is_licensed_content and channel_risk == "medium":
            result.is_safe = True
            result.risk_level = "medium"
            result.reason = "No Content ID + medium-risk channel — clip with transformative edits."
            return result

        # Content ID tracked but low-risk channel = still OK with caution
        if result.is_licensed_content and channel_risk == "low":
            result.is_safe = True
            result.risk_level = "medium"
            result.reason = "Content ID tracked but low-risk channel — clip with heavy edits."
            return result

        # Everything else = high risk
        if channel_risk == "high":
            result.is_safe = False
            result.risk_level = "high"
            result.reason = f"High-risk channel — skipping to avoid copyright strike."
            return result

        # Content ID + medium risk = borderline, allow but warn
        if result.is_licensed_content and channel_risk == "medium":
            result.is_safe = True
            result.risk_level = "medium"
            result.reason = "Content ID tracked + medium-risk — use with heavy transformative edits."
            return result

        result.reason = "Could not determine safety — defaulting to high risk."
        return result

    def _check_via_api(self, video_id: str) -> Optional[dict]:
        """Fetches license and Content ID info via YouTube Data API v3."""
        try:
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "status,contentDetails",
                "id": video_id,
                "key": self.api_key,
            }
            response = http_requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data.get("items"):
                logger.warning(f"No video data for copyright check: {video_id}")
                return None

            item = data["items"][0]
            status = item.get("status", {})
            content_details = item.get("contentDetails", {})

            return {
                "license": status.get("license", "youtube"),
                "licensedContent": content_details.get("licensedContent", False),
                "privacyStatus": status.get("privacyStatus", "public"),
            }
        except Exception as e:
            logger.error(f"Copyright API check failed: {e}")
            return None

    def is_safe_to_clip(self, video_id: str, channel_risk: str = "medium") -> bool:
        """Quick boolean check — is this video safe to clip?"""
        result = self.check_video(video_id, channel_risk)
        logger.info(f"Copyright Check [{video_id}]: safe={result.is_safe}, risk={result.risk_level}, reason={result.reason}")
        return result.is_safe

checker = CopyrightCheckerService()
