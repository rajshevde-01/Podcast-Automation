import os
import re
import isodate
import requests as http_requests
import yt_dlp
from typing import List, Optional, Dict
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from loguru import logger
from ..config import settings
from ..models import ChannelInfo

class YouTubeService:
    def __init__(self,
                 client_id: str = settings.YOUTUBE_CLIENT_ID,
                 client_secret: str = settings.YOUTUBE_CLIENT_SECRET,
                 refresh_token: str = settings.YOUTUBE_REFRESH_TOKEN,
                 api_key: str = settings.YOUTUBE_API_KEY):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.api_key = api_key
        self._youtube_auth = None  # Authenticated client (for uploads)
        self._youtube_public = None  # Public API-key client (for reads)

    @property
    def youtube_auth(self):
        """Authenticated YouTube client — used for uploads only."""
        if self._youtube_auth is None:
            if not all([self.client_id, self.client_secret, self.refresh_token]):
                raise ValueError("YouTube OAuth credentials are not fully set. Cannot upload.")
            
            creds = Credentials(
                None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
            self._youtube_auth = build("youtube", "v3", credentials=creds)
        return self._youtube_auth

    # Keep backward compat
    @property
    def youtube(self):
        return self.youtube_auth

    def get_channel_info(self, channel_id: str) -> Optional[ChannelInfo]:
        """
        Fetches rich metadata about a YouTube channel via the Data API.
        Returns subscriber count, total videos, description, country, etc.
        """
        if not self.api_key:
            logger.warning("No API key — cannot fetch channel info.")
            return None

        try:
            url = "https://www.googleapis.com/youtube/v3/channels"
            params = {
                "part": "snippet,statistics,brandingSettings",
                "id": channel_id,
                "key": self.api_key,
            }
            response = http_requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data.get("items"):
                logger.warning(f"No channel found for ID: {channel_id}")
                return None

            item = data["items"][0]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})

            return ChannelInfo(
                channel_id=channel_id,
                name=snippet.get("title", "Unknown"),
                subscriber_count=int(stats.get("subscriberCount", 0)),
                total_videos=int(stats.get("videoCount", 0)),
                description=snippet.get("description", "")[:500],
                country=snippet.get("country"),
                custom_url=snippet.get("customUrl"),
            )
        except Exception as e:
            logger.error(f"Channel info fetch failed: {e}")
            return None

    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """
        Fetches official metadata for a video using the YouTube Data API.
        Now includes license type, licensedContent flag, and content rating.
        """
        logger.info(f"Fetching metadata for: {video_id}")
        
        # Strategy 1: Use YouTube Data API with API key (most reliable)
        if self.api_key:
            return self._fetch_metadata_api_key(video_id)
        
        # Strategy 2: Use OAuth client (if available)
        if all([self.client_id, self.client_secret, self.refresh_token]):
            result = self._fetch_metadata_oauth(video_id)
            if result:
                return result
        
        # Strategy 3: Use oembed endpoint (no auth needed, but no duration)
        return self._fetch_metadata_oembed(video_id)

    def _fetch_metadata_api_key(self, video_id: str) -> Optional[Dict]:
        """Fetch metadata using YouTube Data API v3 with an API key (no OAuth).
        Extended to include license, licensedContent, and content rating info."""
        try:
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "snippet,contentDetails,status",
                "id": video_id,
                "key": self.api_key,
            }
            response = http_requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data.get("items"):
                logger.warning(f"No video found for ID: {video_id}")
                return None
                
            item = data["items"][0]
            snippet = item["snippet"]
            content_details = item["contentDetails"]
            status = item.get("status", {})
            
            duration_iso = content_details.get("duration")
            duration_seconds = int(isodate.parse_duration(duration_iso).total_seconds())
            
            return {
                "id": video_id,
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "duration": duration_seconds,
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                "channel_title": snippet.get("channelTitle"),
                "channel_id": snippet.get("channelId"),
                # New copyright-relevant fields
                "license": status.get("license", "youtube"),
                "licensed_content": content_details.get("licensedContent", False),
                "content_rating": content_details.get("contentRating", {}),
                "privacy_status": status.get("privacyStatus", "public"),
            }
        except Exception as e:
            logger.error(f"API Key metadata fetch failed: {e}")
            return None

    def _fetch_metadata_oauth(self, video_id: str) -> Optional[Dict]:
        """Fetch metadata using OAuth-authenticated client."""
        try:
            request = self.youtube_auth.videos().list(
                part="snippet,contentDetails,status",
                id=video_id
            )
            response = request.execute()
            
            if not response.get("items"):
                logger.warning(f"No video found for ID: {video_id}")
                return None
                
            item = response["items"][0]
            snippet = item["snippet"]
            content_details = item["contentDetails"]
            status = item.get("status", {})
            
            duration_iso = content_details.get("duration")
            duration_seconds = int(isodate.parse_duration(duration_iso).total_seconds())
            
            return {
                "id": video_id,
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "duration": duration_seconds,
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                "channel_title": snippet.get("channelTitle"),
                "channel_id": snippet.get("channelId"),
                "license": status.get("license", "youtube"),
                "licensed_content": content_details.get("licensedContent", False),
                "content_rating": content_details.get("contentRating", {}),
                "privacy_status": status.get("privacyStatus", "public"),
            }
        except Exception as e:
            logger.error(f"OAuth metadata fetch failed: {e}")
            return None

    def _fetch_metadata_oembed(self, video_id: str) -> Optional[Dict]:
        """
        Fallback: Use YouTube oEmbed endpoint for title,
        then yt-dlp to extract duration (since oEmbed doesn't provide it).
        """
        try:
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = http_requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # oEmbed gives title but NOT duration — use yt-dlp to get duration
            duration = self._get_duration_via_ytdlp(video_id)
            
            return {
                "id": video_id,
                "title": data.get("title", "Unknown"),
                "description": "",
                "duration": duration,
                "thumbnail": data.get("thumbnail_url"),
                "channel_title": data.get("author_name", "Unknown"),
                "channel_id": None,
                "license": "youtube",
                "licensed_content": False,
                "content_rating": {},
                "privacy_status": "public",
            }
        except Exception as e:
            logger.error(f"oEmbed metadata fetch failed: {e}")
            return None

    def _get_duration_via_ytdlp(self, video_id: str) -> int:
        """Extract video duration via yt-dlp metadata (no download)."""
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'extract_flat': False,
            }
            cookies_path = str(settings.BASE_DIR / "cookies.txt")
            if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0:
                opts['cookiefile'] = cookies_path

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                duration = info.get('duration', 0) or 0
                logger.info(f"yt-dlp duration for {video_id}: {duration}s")
                return int(duration)
        except Exception as e:
            logger.warning(f"yt-dlp duration extraction failed: {e}")
            return 0

    def upload_video(self,
                      file_path: str,
                      title: str,
                      description: str,
                      tags: List[str],
                      thumbnail_path: Optional[str] = None) -> Optional[str]:
        
        logger.info(f"Uploading Video: {title}")
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        
        try:
            request = self.youtube_auth.videos().insert(part="snippet,status", body=body, media_body=media)
            response = request.execute()
            video_id = response.get("id")
            video_url = f"https://youtube.com/shorts/{video_id}"
            logger.info(f"✅ Upload successful: {video_url}")

            if thumbnail_path and os.path.exists(thumbnail_path):
                self.upload_thumbnail(video_id, thumbnail_path)
            
            return video_url
        except Exception as e:
            logger.error(f"YouTube Upload Failed: {e}")
            return None

    def upload_thumbnail(self, video_id: str, thumbnail_path: str):
        logger.info(f"Uploading Thumbnail for {video_id}...")
        try:
            self.youtube_auth.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            ).execute()
            logger.info("✅ Thumbnail Uploaded Successfully.")
        except Exception as e:
            logger.warning(f"Thumbnail Upload Failed: {e}")

    def get_channel_latest_videos(self, channel_id: str, max_results: int = 5) -> List[Dict]:
        """
        Fetches the latest videos from a channel using the official Data API.
        Falls back to RSS if no API key is set.
        """
        logger.info(f"Fetching latest videos for channel: {channel_id}")
        
        # If no API key, skip the API call entirely and return empty
        # (the caller will fall back to RSS)
        if not self.api_key:
            logger.warning("No YOUTUBE_API_KEY set — skipping Data API channel fetch.")
            return []
        
        try:
            # 1. Get the uploads playlist ID
            url_channel = "https://www.googleapis.com/youtube/v3/channels"
            params_channel = {
                "part": "contentDetails",
                "id": channel_id,
                "key": self.api_key,
            }
            res_channel = http_requests.get(url_channel, params=params_channel, timeout=10)
            res_channel.raise_for_status()
            data_channel = res_channel.json()
            
            if not data_channel.get("items"):
                logger.warning(f"No channel found for ID: {channel_id}. Trying UU shortcut fallback...")
                uploads_playlist_id = "UU" + channel_id[2:]
            else:
                uploads_playlist_id = data_channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            # 2. List playlist items
            url = "https://www.googleapis.com/youtube/v3/playlistItems"
            params = {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": max_results,
                "key": self.api_key,
            }
            response = http_requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            videos = []
            for item in data.get("items", []):
                snippet = item["snippet"]
                content_details = item["contentDetails"]
                video_id = content_details["videoId"]
                videos.append({
                    "id": video_id,
                    "title": snippet["title"],
                    "url": f"https://www.youtube.com/watch?v={video_id}"
                })
            
            return videos
        except Exception as e:
            logger.error(f"Official Channel Fetch Failed: {e}")
            return []

youtube_service = YouTubeService()
