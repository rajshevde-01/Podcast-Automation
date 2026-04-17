import os
import json
import random
import re
import time
import xml.etree.ElementTree as ET
import requests
import subprocess
from typing import Optional, Dict, List
import yt_dlp
from loguru import logger
from ..config import settings
from ..models import Podcast
from .youtube import youtube_service


class DownloadService:
    def __init__(self):
        # yt-dlp base options — no cookies required
        self.base_opts = {
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'extract_flat': False,
            'user_agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/121.0.0.0 Safari/537.36'
            ),
            'add_header': [
                'Accept-Language: en-US,en;q=0.9',
                'Origin: https://www.youtube.com',
                'Referer: https://www.youtube.com/',
            ],
            'nocheckcertificate': True,
            'youtube_include_dash_manifest': False,
            'geo_bypass': True,
        }

    # ------------------------------------------------------------------
    # Episode discovery
    # ------------------------------------------------------------------

    def get_random_podcast(self) -> Optional[Podcast]:
        """Selects a random podcast from the list."""
        if not os.path.exists(settings.PODCASTS_LIST_FILE):
            logger.error(f"Podcasts list file not found: {settings.PODCASTS_LIST_FILE}")
            return None
        with open(settings.PODCASTS_LIST_FILE, 'r') as f:
            data = json.load(f)
        india_pods = data.get("india_top_10", [])
        world_pods = data.get("world_top_20", [])
        if india_pods and (not world_pods or random.random() < 0.75):
            choice = random.choice(india_pods)
        elif world_pods:
            choice = random.choice(world_pods)
        else:
            return None
        return Podcast(**choice)

    def fetch_latest_episode(self, podcast: Podcast) -> Optional[Dict]:
        """
        Official YouTube Data API discovery — 100% reliable.
        Falls back to YouTube channel RSS if API key is not set.
        """
        if not podcast.channel_id:
            logger.error(f"Channel ID missing for {podcast.name}")
            return None

        logger.info(f"Discovering latest episode for {podcast.name}...")
        videos = youtube_service.get_channel_latest_videos(podcast.channel_id, max_results=10)

        if not videos:
            logger.warning("Official API found no videos. Falling back to YouTube RSS...")
            return self._fetch_from_youtube_rss(podcast)

        for video in videos:
            logger.info(f"Checking video: {video['title']}")
            info = youtube_service.get_video_metadata(video['id'])
            if not info:
                continue
            duration = info.get('duration', 0)
            if duration > settings.MIN_EPISODE_DURATION:
                logger.info(f"✅ Found valid episode: {info['title']} ({duration}s)")
                return info
            else:
                logger.info(f"⏭️ Skipping {info['title']} (too short: {duration}s)")

        logger.error(f"No long-form episodes found among last 10 uploads for {podcast.name}")
        return None

    def _fetch_from_youtube_rss(self, podcast: Podcast) -> Optional[Dict]:
        """Backup discovery using YouTube's public channel RSS feed (video IDs only)."""
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={podcast.channel_id}"
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            video_ids = re.findall(r'<yt:videoId>(.*?)</yt:videoId>', res.text)
            for vid_id in video_ids[:5]:
                info = youtube_service.get_video_metadata(vid_id)
                if info and info.get('duration', 0) > settings.MIN_EPISODE_DURATION:
                    return info
        except Exception as e:
            logger.warning(f"YouTube RSS fallback failed: {e}")
        return None

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    def _parse_itunes_duration(self, duration_str: str) -> int:
        """Parse iTunes duration (HH:MM:SS, MM:SS, or plain seconds) → seconds."""
        try:
            parts = duration_str.strip().split(':')
            if len(parts) == 1:
                return int(float(parts[0]))
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except Exception:
            pass
        return 0

    def _download_url_with_retry(
        self, url: str, output_path: str, max_retries: int = 3
    ) -> bool:
        """Download a URL to *output_path* with exponential-backoff retries."""
        for attempt in range(max_retries):
            try:
                r = requests.get(
                    url,
                    stream=True,
                    timeout=120,
                    headers={'User-Agent': 'Mozilla/5.0'},
                )
                r.raise_for_status()

                content_type = r.headers.get('Content-Type', '')
                if 'text/html' in content_type:
                    logger.warning(f"Received HTML instead of audio/video at {url}")
                    return False

                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                    return True
                logger.warning(f"Downloaded file too small, attempt {attempt + 1}")

            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Download attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"All {max_retries} download attempts failed for {url}: {e}")
        return False

    # ------------------------------------------------------------------
    # RSS audio acquisition (Layer 1 — no YouTube auth needed)
    # ------------------------------------------------------------------

    def _download_audio_from_rss(self, podcast: Podcast) -> Optional[str]:
        """
        Download audio from the podcast's own RSS feed enclosure URL.
        Requires `podcast.rss_feed` to be set.  Skips episodes shorter than
        MIN_EPISODE_DURATION when iTunes duration metadata is available.
        """
        if not podcast.rss_feed:
            return None

        logger.info(f"RSS Strategy: fetching feed for '{podcast.name}' → {podcast.rss_feed}")
        try:
            res = requests.get(
                podcast.rss_feed,
                timeout=20,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; PodcastBot/1.0)'},
            )
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"RSS feed fetch failed for {podcast.name}: {e}")
            return None

        try:
            root = ET.fromstring(res.content)
        except ET.ParseError as e:
            logger.warning(f"RSS feed XML parse error for {podcast.name}: {e}")
            return None

        itunes_ns = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
        items = root.findall('.//item')
        if not items:
            logger.warning(f"RSS feed for '{podcast.name}' has no <item> entries")
            return None

        for item in items[:5]:  # check up to 5 most-recent episodes
            enclosure = item.find('enclosure')
            if enclosure is None:
                continue

            audio_url = enclosure.get('url', '').strip()
            if not audio_url:
                continue

            # Validate content type
            enc_type = enclosure.get('type', '').lower()
            is_audio_type = any(t in enc_type for t in ('audio', 'mpeg', 'm4a', 'mp4'))
            is_audio_ext = any(
                audio_url.lower().endswith(ext)
                for ext in ('.mp3', '.m4a', '.mp4', '.aac', '.ogg')
            )
            if not is_audio_type and not is_audio_ext:
                logger.debug(f"Skipping non-audio enclosure (type={enc_type}): {audio_url}")
                continue

            # Duration gate (skip episodes that are too short)
            duration_el = item.find(f'{{{itunes_ns}}}duration')
            if duration_el is not None and duration_el.text:
                dur_secs = self._parse_itunes_duration(duration_el.text)
                if 0 < dur_secs < settings.MIN_EPISODE_DURATION:
                    title_el = item.find('title')
                    ep_title = title_el.text if title_el is not None else audio_url
                    logger.info(f"⏭️ Skipping RSS episode '{ep_title}' (too short: {dur_secs}s)")
                    continue

            title_el = item.find('title')
            ep_title = title_el.text if title_el is not None else "Unknown"
            logger.info(f"RSS: downloading episode '{ep_title}'")

            # Determine extension from URL or type
            ext = 'm4a'
            for candidate in ('.mp3', '.m4a', '.mp4', '.aac'):
                if candidate in audio_url.lower():
                    ext = candidate.lstrip('.')
                    break

            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', podcast.name)[:20]
            output_path = str(settings.DATA_DIR / f"temp_audio_rss_{safe_name}.{ext}")

            if self._download_url_with_retry(audio_url, output_path):
                logger.info(f"✅ RSS audio download successful: {output_path}")
                return output_path

        logger.warning(f"RSS: no suitable episode found in feed for '{podcast.name}'")
        return None

    # ------------------------------------------------------------------
    # RapidAPI (Layer 2 — YouTube fallback, no cookies)
    # ------------------------------------------------------------------

    def _get_rapidapi_stream_url(
        self, video_url: str, is_audio: bool = False
    ) -> Optional[str]:
        """
        Resolve a downloadable stream URL via RapidAPI.
        Returns None (with a clear log message) when the key is missing or
        when the API returns an error.
        """
        if not settings.RAPID_API_KEY:
            logger.info("RapidAPI skipped: RAPID_API_KEY not configured.")
            return None

        logger.info("RapidAPI: resolving stream URL...")
        api_url = "https://youtube-download-video-and-audio-v2.p.rapidapi.com/v1/download"
        headers = {
            "X-RapidAPI-Key": settings.RAPID_API_KEY,
            "X-RapidAPI-Host": "youtube-download-video-and-audio-v2.p.rapidapi.com",
        }
        try:
            res = requests.get(
                api_url,
                headers=headers,
                params={"url": video_url},
                timeout=30,
            )

            if res.status_code == 401:
                logger.error(
                    "RapidAPI returned 401 Unauthorized. "
                    "Check that RAPID_API_KEY is correct."
                )
                return None
            if res.status_code == 403:
                logger.error(
                    "RapidAPI returned 403 Forbidden. "
                    "Subscription to 'youtube-download-video-and-audio-v2' may be inactive or quota exhausted. "
                    "Visit https://rapidapi.com to check your plan."
                )
                return None
            if res.status_code == 429:
                logger.error(
                    "RapidAPI returned 429 Too Many Requests. "
                    "Daily/monthly quota exceeded for your RapidAPI plan."
                )
                return None

            res.raise_for_status()
            data = res.json()

            streams = data.get("streams", [])
            if not streams:
                logger.warning(
                    f"RapidAPI returned no streams. Full response: {str(data)[:200]}"
                )
                return None

            if is_audio:
                target = next(
                    (s for s in streams if s.get("type") == "audio"), None
                )
            else:
                target = next(
                    (
                        s
                        for s in streams
                        if s.get("type") == "video" and s.get("quality") == "1080p"
                    ),
                    None,
                )
                if not target:
                    target = next(
                        (s for s in streams if s.get("type") == "video"), None
                    )

            if not target or "url" not in target:
                logger.warning(
                    "RapidAPI: no suitable stream found in response. "
                    f"Available types: {[s.get('type') for s in streams]}"
                )
                return None

            logger.info(
                f"✅ RapidAPI resolved stream URL "
                f"(type={target.get('type')}, quality={target.get('quality', 'n/a')})"
            )
            return target["url"]

        except Exception as e:
            logger.warning(f"RapidAPI request failed: {e}")
            return None

    def _download_via_rapidapi(
        self, video_url: str, output_path: str, is_audio: bool = False
    ) -> bool:
        """Download full media file via RapidAPI."""
        stream_url = self._get_rapidapi_stream_url(video_url, is_audio)
        if not stream_url:
            return False
        logger.info("RapidAPI: downloading stream...")
        return self._download_url_with_retry(stream_url, output_path)

    # ------------------------------------------------------------------
    # Public download methods
    # ------------------------------------------------------------------

    def download_audio(
        self, video_id: str, podcast: Optional[Podcast] = None
    ) -> Optional[str]:
        """
        Download audio for *video_id* using the following strategy:
          1. RSS enclosure (if podcast.rss_feed is set) — no YouTube auth
          2. RapidAPI                                   — no YouTube auth
          3. yt-dlp without cookies                     — fails fast on bot-detection
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_path = str(settings.DATA_DIR / f"temp_audio_{video_id}.m4a")
        if os.path.exists(output_path):
            os.remove(output_path)

        # --- Layer 1: RSS ---
        if podcast and podcast.rss_feed:
            logger.info("📡 Attempting audio download via RSS feed (Layer 1)...")
            rss_path = self._download_audio_from_rss(podcast)
            if rss_path:
                return rss_path
            logger.warning("RSS download failed, falling back to YouTube layers.")
        else:
            logger.info(
                "📡 No RSS feed configured for this podcast — "
                "using YouTube fallback layers."
            )

        # --- Layer 2: RapidAPI ---
        logger.info("📡 Attempting audio download via RapidAPI (Layer 2)...")
        if self._download_via_rapidapi(url, output_path, is_audio=True):
            return output_path

        # --- Layer 3: yt-dlp (no cookies) ---
        logger.info("📡 Attempting audio download via yt-dlp (Layer 3, no cookies)...")
        opts = self.base_opts.copy()
        opts.update({
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': output_path,
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if os.path.exists(output_path):
                return output_path
        except yt_dlp.utils.DownloadError as e:
            err_lower = str(e).lower()
            if any(kw in err_lower for kw in ('sign in', 'bot', 'confirm', 'login required')):
                raise RuntimeError(
                    f"yt-dlp was blocked by YouTube bot-detection for video '{video_id}'. "
                    "To fix this, add an 'rss_feed' URL to this podcast entry in "
                    "podcasts_list.json, or set the RAPID_API_KEY GitHub Actions secret. "
                    "YouTube cookies are no longer supported."
                ) from e
            logger.error(f"yt-dlp audio download failed: {e}")
        except Exception as e:
            logger.error(f"yt-dlp unexpected error: {e}")

        logger.error(
            f"❌ All audio download layers failed for video '{video_id}'. "
            "Check logs above for specific failure reasons."
        )
        return None

    def download_video_segment(
        self, video_id: str, start_time: float, end_time: float
    ) -> Optional[str]:
        """
        Download a video segment for *video_id* using:
          1. RapidAPI stream URL + ffmpeg cut
          2. yt-dlp download_sections (no cookies) — fails fast on bot-detection
          3. pytubefix stream URL + ffmpeg cut
        """
        output_path = str(settings.DATA_DIR / f"temp_segment_{video_id}.mp4")
        if os.path.exists(output_path):
            os.remove(output_path)
        url = f"https://www.youtube.com/watch?v={video_id}"
        duration = end_time - start_time

        # --- Layer 1: RapidAPI → ffmpeg segment ---
        logger.info("📡 Attempting video segment via RapidAPI + ffmpeg (Layer 1)...")
        stream_url = self._get_rapidapi_stream_url(url, is_audio=False)
        if stream_url:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time), "-t", str(duration),
                "-i", stream_url,
                "-c:v", "libx264", "-preset", "veryfast",
                "-c:a", "aac",
                output_path,
            ]
            try:
                subprocess.run(
                    cmd, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if os.path.exists(output_path):
                    logger.info("✅ RapidAPI + ffmpeg segment success.")
                    return output_path
            except subprocess.CalledProcessError as e:
                logger.warning(f"ffmpeg segment cut failed: {e}")

        # --- Layer 2: yt-dlp sections ---
        logger.info("📡 Attempting video segment via yt-dlp sections (Layer 2, no cookies)...")
        opts = self.base_opts.copy()
        opts.update({
            'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_path,
            # yt-dlp section syntax: "*START-END" where values are seconds (float ok)
            'download_sections': f"*{start_time}-{end_time}",
            'force_keyframes_at_cuts': True,
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if os.path.exists(output_path):
                return output_path
        except yt_dlp.utils.DownloadError as e:
            err_lower = str(e).lower()
            if any(kw in err_lower for kw in ('sign in', 'bot', 'confirm', 'login required')):
                raise RuntimeError(
                    f"yt-dlp was blocked by YouTube bot-detection for video '{video_id}'. "
                    "Set RAPID_API_KEY in GitHub Actions secrets to enable the RapidAPI "
                    "download layer. YouTube cookies are no longer supported."
                ) from e
            logger.warning(f"yt-dlp segment download failed: {e}")
        except Exception as e:
            logger.warning(f"yt-dlp unexpected error: {e}")

        # --- Layer 3: pytubefix stream URL + ffmpeg ---
        logger.info("📡 Attempting video segment via pytubefix + ffmpeg (Layer 3)...")
        try:
            from pytubefix import YouTube  # imported here to keep it an optional dep
            yt = YouTube(url)
            stream = (
                yt.streams.filter(progressive=True, file_extension='mp4')
                .order_by('resolution')
                .desc()
                .first()
            )
            if stream:
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start_time), "-t", str(duration),
                    "-i", stream.url,
                    "-c:v", "libx264", "-preset", "veryfast",
                    "-c:a", "aac",
                    output_path,
                ]
                subprocess.run(
                    cmd, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if os.path.exists(output_path):
                    logger.info("✅ pytubefix + ffmpeg segment success.")
                    return output_path
        except Exception as e:
            logger.warning(f"pytubefix segment download failed: {e}")

        logger.error(
            f"❌ All video segment download layers failed for video '{video_id}'. "
            "Check logs above for specific failure reasons."
        )
        return None


downloader = DownloadService()
