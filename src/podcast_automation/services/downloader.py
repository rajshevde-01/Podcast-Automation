import os
import json
import random
import re
import requests
import subprocess
from typing import Optional, Tuple, Dict
import yt_dlp
from pytubefix import YouTube
from pytubefix.cli import on_progress
from loguru import logger
from ..config import settings
from ..models import Podcast
from .youtube import youtube_service

class DownloadService:
    def __init__(self, cookies_path: str = settings.COOKIES_FILE):
        self.cookies_path = cookies_path
        self.base_opts = {
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'extract_flat': False,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'add_header': [
                'Accept-Language: en-US,en;q=0.9',
                'Origin: https://www.youtube.com',
                'Referer: https://www.youtube.com/',
                'Sec-Fetch-Mode: navigate',
                'Sec-Fetch-Site: same-origin',
                'Sec-Fetch-Dest: document',
                'Upgrade-Insecure-Requests: 1'
            ],
            'nocheckcertificate': True,
            'youtube_include_dash_manifest': False,
            'geo_bypass': True,
        }
        if os.path.exists(self.cookies_path) and os.path.getsize(self.cookies_path) > 0:
            self.base_opts['cookiefile'] = self.cookies_path
            logger.info(f"Using cookies from {self.cookies_path}")

    def get_random_podcast(self) -> Optional[Podcast]:
        if not os.path.exists(settings.PODCASTS_LIST_FILE):
            logger.error(f"Podcasts list file not found: {settings.PODCASTS_LIST_FILE}")
            return None
        
        with open(settings.PODCASTS_LIST_FILE, 'r') as f:
            data = json.load(f)
        
        india_pods = data.get("india_top_10", [])
        world_pods = data.get("world_top_20", [])
        
        # 75% chance for India
        if india_pods and (not world_pods or random.random() < 0.75):
            choice = random.choice(india_pods)
        elif world_pods:
            choice = random.choice(world_pods)
        else:
            return None
            
        return Podcast(**choice)

    def _fetch_from_rss(self, channel_id: str) -> Optional[Dict]:
        """Fetches the latest videos using YouTube's RSS feed."""
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        logger.info(f"Fetching RSS feed: {rss_url}")
        
        try:
            response = requests.get(rss_url, timeout=10)
            response.raise_for_status()
            xml_content = response.text
            
            entries = re.findall(r'<entry>(.*?)</entry>', xml_content, re.DOTALL)
            if not entries:
                return None
                
            results = []
            for entry in entries:
                video_id_match = re.search(r'<yt:videoId>(.*?)</yt:videoId>', entry)
                title_match = re.search(r'<title>(.*?)</title>', entry)
                
                if video_id_match and title_match:
                    results.append({
                        'id': video_id_match.group(1),
                        'title': title_match.group(1),
                        'url': f"https://www.youtube.com/watch?v={video_id_match.group(1)}"
                    })
            
            metadata_failures = 0
            for item in results:
                logger.info(f"Checking video from RSS: {item['title']}")
                info = youtube_service.get_video_metadata(item['id'])
                if not info:
                    metadata_failures += 1
                    continue
                    
                duration = info.get('duration', 0)
                if duration == 0:
                    title_lower = item['title'].lower()
                    if any(skip_word in title_lower for skip_word in ['clip', 'shorts', 'short', 'trailer', 'teaser']):
                        logger.info(f"⏭️ Skipping {item['title']} (Looks like a clip, no duration data)")
                        continue
                    logger.info(f"✅ Accepting episode via fallback (no duration data): {info['title']}")
                    return info
                elif duration > settings.MIN_EPISODE_DURATION:
                    logger.info(f"✅ Found valid episode via Data API: {info['title']} ({duration}s)")
                    return info
                else:
                    logger.info(f"⏭️ Skipping {info['title']} (Too short: {duration}s)")
            
            if metadata_failures == len(results):
                logger.error("⚠️ ALL metadata calls failed. Check YOUTUBE_API_KEY!")
                    
            return None
        except Exception as e:
            logger.error(f"RSS Fetch Error: {e}")
            return None

    def fetch_latest_episode(self, podcast: Podcast) -> Optional[Dict]:
        """Fetches metadata for the latest episode, trying RSS first then yt-dlp/pytubefix."""
        if podcast.channel_id:
            entry = self._fetch_from_rss(podcast.channel_id)
            if entry:
                return entry
        
        channel_url = podcast.url
        logger.info(f"RSS failed. Running bypass fetch for {channel_url}...")
        
        # Strategy A: yt-dlp with specific clients
        profiles = [
            {"name": "Android App", "args": {'youtube': {'player_client': ['android']}}},
            {"name": "iOS App", "args": {'youtube': {'player_client': ['ios']}}},
        ]
        
        for profile in profiles:
            opts = self.base_opts.copy()
            opts['extractor_args'] = profile['args']
            opts['playlist_items'] = '5'
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
                    if 'entries' in info and info['entries']:
                        for entry in info['entries']:
                            if not entry: continue
                            if entry.get('duration', 0) > settings.MIN_EPISODE_DURATION:
                                logger.info(f"✅ Success with yt-dlp ({profile['name']}): {entry['title']}")
                                return entry
            except Exception as e:
                logger.warning(f"yt-dlp profile {profile['name']} failed: {str(e).splitlines()[0]}")

        # Strategy B: pytubefix (Very resilient)
        try:
            logger.info("Trying pytubefix for metadata...")
            from pytubefix import Channel
            c = Channel(channel_url)
            for video in c.videos[:5]:
                if video.length > settings.MIN_EPISODE_DURATION:
                    logger.info(f"✅ Success with pytubefix: {video.title}")
                    return {'id': video.video_id, 'title': video.title, 'duration': video.length, 'url': video.watch_url}
        except Exception as e:
            logger.warning(f"pytubefix metadata fetch failed: {e}")

        logger.error("🛑 ALL fetch strategies failed.")
        return None

    def download_audio(self, video_id: str) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_audio_{video_id}.m4a")
        if os.path.exists(output_path): os.remove(output_path)
            
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. yt-dlp
        logger.info(f"Download Layer 1 (yt-dlp): {url}")
        opts = self.base_opts.copy()
        opts.update({
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': output_path,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.warning(f"Layer 1 Failed: {str(e).splitlines()[0]}")

        # 2. pytubefix
        logger.info(f"Download Layer 2 (pytubefix): {url}")
        try:
            yt = YouTube(url)
            audio_stream = yt.streams.get_audio_only()
            # Pytubefix download takes filename as argument
            audio_stream.download(output_path=str(settings.DATA_DIR), filename=f"temp_audio_{video_id}.m4a")
            if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.warning(f"Layer 2 Failed: {e}")

        # 3. Cobalt API (v10)
        logger.info(f"Download Layer 3 (Cobalt API v10): {url}")
        try:
            cobalt_url = "https://api.cobalt.tools/"
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            payload = {
                "url": url,
                "downloadMode": "audio",
                "audioFormat": "m4a"
            }
            res = requests.post(cobalt_url, json=payload, headers=headers, timeout=30)
            data = res.json()
            if (data.get("status") in ["stream", "redirect", "picker"] or "url" in data) and data.get("url"):
                stream_url = data["url"]
                r = requests.get(stream_url, stream=True)
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024*1024): f.write(chunk)
                return output_path
        except Exception as e:
            logger.error(f"Layer 3 Failed: {e}")

        return None

    def download_video_segment(self, video_id: str, start_time: float, end_time: float) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_segment_{video_id}.mp4")
        if os.path.exists(output_path): os.remove(output_path)
        url = f"https://www.youtube.com/watch?v={video_id}"
        duration = end_time - start_time

        # 1. yt-dlp (Most efficient if it works)
        logger.info(f"Segment Layer 1 (yt-dlp sections): {url}")
        opts = self.base_opts.copy()
        opts.update({
            'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_path,
            'download_sections': f"*{start_time}-{end_time}",
            'force_keyframes_at_cuts': True,
            'extractor_args': {'youtube': {'player_client': ['android']}},
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.warning(f"Segment Layer 1 Failed: {str(e).splitlines()[0]}")

        # 2. pytubefix + ffmpeg stream cut
        logger.info(f"Segment Layer 2 (pytubefix + ffmpeg cut): {url}")
        try:
            yt = YouTube(url)
            stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            if stream:
                stream_url = stream.url
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-t", str(duration),
                    "-i", stream_url,
                    "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                    output_path
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.warning(f"Segment Layer 2 Failed: {e}")

        # 3. Cobalt Fallback
        logger.info(f"Segment Layer 3 (Cobalt Fallback): {url}")
        try:
            cobalt_url = "https://api.cobalt.tools/"
            res = requests.post(cobalt_url, json={"url": url, "videoQuality": "1080"}, headers={"Accept": "application/json", "Content-Type": "application/json"})
            data = res.json()
            if data.get("url"):
                stream_url = data["url"]
                cmd = ["ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration), "-i", stream_url, "-c", "copy", output_path]
                subprocess.run(cmd, check=True)
                if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.error(f"Segment Layer 3 Failed: {e}")

        return None

downloader = DownloadService()
