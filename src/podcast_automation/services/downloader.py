import os
import json
import random
import re
import requests
import subprocess
from typing import Optional, Tuple, Dict, List
import yt_dlp
from pytubefix import YouTube
from loguru import logger
from ..config import settings
from ..models import Podcast
from .youtube import youtube_service

class DownloadService:
    def __init__(self, cookies_path: str = settings.COOKIES_FILE):
        self.cookies_path = cookies_path
        self.cobalt_instances = [
            "https://nachos.imput.net/",
            "https://blossom.imput.net/",
            "https://kityune.imput.net/",
            "https://api.cobalt.tools/"
        ]
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
            ],
            'nocheckcertificate': True,
            'youtube_include_dash_manifest': False,
            'geo_bypass': True,
        }
        if os.path.exists(self.cookies_path) and os.path.getsize(self.cookies_path) > 0:
            self.base_opts['cookiefile'] = self.cookies_path

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
        New Logic (v3): Fetches latest episodes using OFFICIAL YouTube Data API.
        This is 100% reliable and bypasses all bot detection challenges.
        """
        if not podcast.channel_id:
            logger.error(f"Channel ID missing for {podcast.name}")
            return None
            
        logger.info(f"Official Discovery: Finding latest videos for {podcast.name}...")
        videos = youtube_service.get_channel_latest_videos(podcast.channel_id, max_results=10)
        
        if not videos:
            logger.warning(f"Official API found no videos for {podcast.name}. Usage history or Quota issue?")
            return None
            
        for video in videos:
            logger.info(f"Checking video: {video['title']}")
            # Use Data API for metadata (duration)
            info = youtube_service.get_video_metadata(video['id'])
            if not info:
                continue
                
            duration = info.get('duration', 0)
            if duration > settings.MIN_EPISODE_DURATION:
                logger.info(f"✅ Found valid episode: {info['title']} ({duration}s)")
                return info
            else:
                logger.info(f"⏭️ Skipping {info['title']} (Too short: {duration}s)")
                
        logger.error(f"No long-form episodes found among last 10 uploads for {podcast.name}")
        return None

    def _download_via_cobalt(self, video_url: str, output_path: str, is_audio: bool = False, start_time: float = None, end_time: float = None) -> bool:
        """Downloads/Slices media using the Cobalt API (Primary Layer)."""
        logger.info(f"Attempting download via Cobalt Bridge...")
        
        for instance in self.cobalt_instances:
            try:
                payload = {
                    "url": video_url,
                    "downloadMode": "audio" if is_audio else "default",
                    "videoQuality": "1080",
                    "audioFormat": "best",
                    "youtubeVideoCodec": "h264",
                    "alwaysProxy": True # Help bypass GHA IP blocks
                }
                res = requests.post(instance, json=payload, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=30)
                logger.info(f"Cobalt Request to {instance}: Status {res.status_code}")
                data = res.json()
                
                status = data.get("status")
                if status == "error":
                    logger.warning(f"Cobalt Error ({instance}): {data.get('text')}")
                    continue
                elif status == "rate-limit":
                    logger.warning(f"Cobalt Rate-Limit ({instance})")
                    continue
                elif status == "redirect":
                    # Some instances redirect to the file
                    stream_url = data.get("url")
                else:
                    # Success
                    stream_url = data.get("url")
                    
                if not stream_url:
                    logger.warning(f"Cobalt Instance {instance} returned no URL: {data}")
                    continue
                    
                logger.info(f"Cobalt accepted query. Retrieving stream...")
                
                # If segment slicing is needed, use ffmpeg on the stream URL
                if start_time is not None and end_time is not None:
                    duration = end_time - start_time
                    cmd = [
                        "ffmpeg", "-y",
                        "-ss", str(start_time), "-t", str(duration),
                        "-i", stream_url,
                        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                        output_path
                    ]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    # Direct download
                    r = requests.get(stream_url, stream=True, timeout=60)
                    r.raise_for_status()
                    with open(output_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            f.write(chunk)
                
                if os.path.exists(output_path):
                    logger.info("✅ Cobalt download successful.")
                    return True
            except Exception as e:
                logger.warning(f"Cobalt Instance {instance} failed: {e}")
                
        return False

    def download_audio(self, video_id: str) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_audio_{video_id}.m4a")
        if os.path.exists(output_path): os.remove(output_path)
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. Cobalt (Primary)
        if self._download_via_cobalt(url, output_path, is_audio=True):
            return output_path
            
        # 2. yt-dlp (Fallback)
        logger.info("Layer 2 Fallback: yt-dlp")
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
            logger.warning(f"yt-dlp fallback failed: {str(e).splitlines()[0]}")

        # 3. pytubefix (Fallback)
        logger.info("Layer 3 Fallback: pytubefix")
        try:
            yt = YouTube(url)
            audio_stream = yt.streams.get_audio_only()
            audio_stream.download(output_path=str(settings.DATA_DIR), filename=f"temp_audio_{video_id}.m4a")
            if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.error(f"pytubefix fallback failed: {e}")

        return None

    def download_video_segment(self, video_id: str, start_time: float, end_time: float) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_segment_{video_id}.mp4")
        if os.path.exists(output_path): os.remove(output_path)
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. Cobalt (Primary) - Handles both download and slice via stream URL
        if self._download_via_cobalt(url, output_path, is_audio=False, start_time=start_time, end_time=end_time):
            return output_path
            
        # 2. yt-dlp (Fallback)
        logger.info("Layer 2 Fallback: yt-dlp sections")
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
            logger.warning(f"yt-dlp fallback failed: {str(e).splitlines()[0]}")

        # 3. pytubefix + ffmpeg (Fallback)
        logger.info("Layer 3 Fallback: pytubefix + ffmpeg cut")
        try:
            yt = YouTube(url)
            stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            if stream:
                cmd = [
                    "ffmpeg", "-y", "-ss", str(start_time), "-t", str(end_time-start_time),
                    "-i", stream.url,
                    "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                    output_path
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.error(f"pytubefix fallback failed: {e}")

        return None

downloader = DownloadService()
