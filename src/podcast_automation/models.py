from typing import List, Optional
from pydantic import BaseModel, Field

class Podcast(BaseModel):
    name: str
    channel_id: Optional[str] = None
    url: str
    theme: Optional[str] = None
    rss_feed: Optional[str] = None  # Podcast audio RSS feed URL (enables cookie-free audio download)
    category: Optional[str] = None  # e.g. "education", "business", "entertainment", "comedy"

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
    # Advanced fields
    viral_score: float = 0.0       # LLM-assigned 1-10 virality score
    guest_name: Optional[str] = None   # Detected guest name for SEO
    topic: Optional[str] = None        # Main topic/theme of the highlight

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
    # Analytics fields (populated by analytics workflow)
    views: int = 0
    likes: int = 0
    comments: int = 0
    analytics_fetched_at: Optional[str] = None
