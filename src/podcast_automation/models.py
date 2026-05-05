from typing import List, Optional
from pydantic import BaseModel, Field

class Podcast(BaseModel):
    name: str
    channel_id: Optional[str] = None
    url: str
    theme: Optional[str] = None
    copyright_risk: str = "medium"  # "low", "medium", "high"
    license_policy: Optional[str] = None  # e.g., "Encourages clips", "Max 60s non-commercial"
    subscriber_count: Optional[int] = None
    category: Optional[str] = None

class ChannelInfo(BaseModel):
    """Rich metadata about a YouTube channel, fetched via Data API."""
    channel_id: str
    name: str
    subscriber_count: int = 0
    total_videos: int = 0
    description: Optional[str] = None
    country: Optional[str] = None
    custom_url: Optional[str] = None
    copyright_risk: str = "medium"

class CopyrightCheckResult(BaseModel):
    """Result of a copyright safety check on a specific video."""
    video_id: str
    license_type: str = "youtube"  # "youtube" (standard) or "creativeCommon"
    is_licensed_content: bool = False  # True = Content ID tracked
    is_safe: bool = False
    risk_level: str = "high"  # "low", "medium", "high"
    reason: str = ""

class Episode(BaseModel):
    id: str
    podcast_name: str
    title: str
    audio_path: Optional[str] = None
    video_path: Optional[str] = None

class Highlight(BaseModel):
    start_time: float
    end_time: float
    title: str
    reason: str
    hashtags: List[str] = Field(default_factory=list)
    b_roll_keyword: Optional[str] = None

class Short(BaseModel):
    id: Optional[int] = None
    episode_id: str
    start_time: float
    end_time: float
    title: str
    video_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    upload_url: Optional[str] = None
    is_uploaded: bool = False
