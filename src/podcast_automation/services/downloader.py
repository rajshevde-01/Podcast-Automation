import os
import json
import random
import re
import requests
from typing import Optional, Tuple, Dict
import yt_dlp
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
            'prefer_free_formats': True,
            'youtube_include_dash_manifest': False,
            'geo_bypass': True,
        }
        if os.path.exists(self.cookies_path):
            self.base_opts['cookiefile'] = self.cookies_path

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
        """
        Fetches the latest videos using YouTube's RSS feed.
        """
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        logger.info(f"Fetching RSS feed: {rss_url}")
        
        try:
            response = requests.get(rss_url, timeout=10)
            response.raise_for_status()
            xml_content = response.text
            
            # Simple regex parsing for entries to avoid feedparser dependency
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
            
            # Since RSS doesn't give duration, we use the OFFICIAL API for info
            # which is 100% reliable and never blocked by bot detection.
            for item in results:
                logger.info(f"Checking video from RSS: {item['title']}")
                info = youtube_service.get_video_metadata(item['id'])
                if not info:
                    continue
                    
                duration = info.get('duration', 0)
                if duration > settings.MIN_EPISODE_DURATION:
                    logger.info(f"✅ Found valid episode via Data API: {info['title']} ({duration}s)")
                    return info
                else:
                    logger.info(f"⏭️ Skipping {info['title']} (Too short: {duration}s)")
                    
            return None
        except Exception as e:
            logger.error(f"RSS Fetch Error: {e}")
            return None

    def fetch_latest_episode(self, podcast: Podcast) -> Optional[Dict]:
        """
        Fetches metadata for the latest episode from a channel.
        Tries RSS first, then falls back to yt-dlp profiles.
        """
        # 1. Try RSS First (Most reliable in Actions)
        if podcast.channel_id:
            entry = self._fetch_from_rss(podcast.channel_id)
            if entry:
                return entry
        
        # 2. Fallback to yt-dlp bypass profiles
        channel_url = podcast.url
        logger.info(f"RSS failed or unavailable. Falling back to yt-dlp for {channel_url}...")
        
        profiles = [
            {"name": "iOS App", "args": "youtube:player-client=ios"},
            {"name": "Android App", "args": "youtube:player-client=android"},
            {"name": "Web/MWeb", "args": "youtube:player-client=web,mweb"},
            {"name": "TV/Embedded", "args": "youtube:player-client=tv,web_embedded"},
        ]
        
        for profile in profiles:
            opts = self.base_opts.copy()
            opts['extractor_args'] = profile['args']
            opts['playlist_items'] = '5'
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
                    if 'entries' in info and len(info['entries']) > 0:
                        for entry in info['entries']:
                            if not entry: continue
                            duration = entry.get('duration', 0)
                            if duration > settings.MIN_EPISODE_DURATION:
                                logger.info(f"✅ Success with profile {profile['name']}! Found: {entry['title']} ({duration}s)")
                                return entry
                            else:
                                logger.info(f"⏭️ Skipping {entry['title']} (Too short: {duration}s)")
                        
                        logger.warning(f"No long-form episodes found in the last 5 uploads for {channel_url}")
                        return None
            except Exception as e:
                # Capture a more descriptive error message
                error_msg = str(e).split('\n')[0]
                logger.warning(f"Profile {profile['name']} failed: {error_msg}")
                continue
        
        logger.error("🛑 ALL bypass profiles failed to fetch metadata. YouTube is likely blocking this runner.")
        return None

    def download_audio(self, video_id: str) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_audio_{video_id}.m4a")
        if os.path.exists(output_path):
            os.remove(output_path)
            
        opts = self.base_opts.copy()
        opts.update({
            'format': 'bestaudio[ext=m4a]/bestaudio',
            'outtmpl': output_path,
            'extractor_args': 'youtube:player-client=ios',
        })
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Downloading audio: {url}")
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
                return output_path
        except Exception as e:
            logger.error(f"Failed to download audio: {e}")
            return None

    def download_video_segment(self, video_id: str, start_time: float, end_time: float) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_segment_{video_id}.mp4")
        if os.path.exists(output_path):
            os.remove(output_path)
            
        opts = self.base_opts.copy()
        opts.update({
            'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best',
            'outtmpl': output_path,
            'download_sections': f"*{start_time}-{end_time}",
            'force_keyframes_at_cuts': True,
            'extractor_args': 'youtube:player-client=ios',
        })
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Downloading video segment {start_time}-{end_time}: {url}")
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
                return output_path
        except Exception as e:
            logger.error(f"Failed to download video segment: {e}")
            return None

downloader = DownloadService()
