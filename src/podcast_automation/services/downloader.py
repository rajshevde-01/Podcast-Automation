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
        
        # Detect if ffmpeg is available
        self.has_ffmpeg = self._check_ffmpeg()
        if not self.has_ffmpeg:
            logger.warning("ffmpeg not found — will use progressive streams (lower quality but works without ffmpeg)")

    def _check_ffmpeg(self) -> bool:
        """Check if ffmpeg is available in PATH."""
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def get_random_podcast(self) -> Optional[Podcast]:
        """Selects a random podcast from the list, skipping high-risk channels."""
        if not os.path.exists(settings.PODCASTS_LIST_FILE):
            logger.error(f"Podcasts list file not found: {settings.PODCASTS_LIST_FILE}")
            return None
        with open(settings.PODCASTS_LIST_FILE, 'r') as f:
            data = json.load(f)
        
        india_pods = data.get("india_top_10", [])
        world_pods = data.get("world_top_20", [])
        
        # Filter out channels exceeding the copyright risk threshold
        def is_safe_channel(pod_dict):
            risk = pod_dict.get("copyright_risk", "medium")
            return not settings.should_skip_risk(risk)
        
        india_safe = [p for p in india_pods if is_safe_channel(p)]
        world_safe = [p for p in world_pods if is_safe_channel(p)]
        
        skipped_india = len(india_pods) - len(india_safe)
        skipped_world = len(world_pods) - len(world_safe)
        if skipped_india or skipped_world:
            logger.info(f"🛡️ Copyright filter: skipped {skipped_india} India + {skipped_world} World channels above '{settings.COPYRIGHT_RISK_THRESHOLD}' risk threshold")
        
        if india_safe and (not world_safe or random.random() < 0.75):
            choice = random.choice(india_safe)
        elif world_safe:
            choice = random.choice(world_safe)
        else:
            logger.error("No safe channels available after copyright filtering!")
            return None
        
        podcast = Podcast(**choice)
        logger.info(f"🎯 Selected: {podcast.name} (risk: {podcast.copyright_risk}, policy: {podcast.license_policy})")
        return podcast

    def fetch_latest_episode(self, podcast: Podcast) -> Optional[Dict]:
        """
        Official YouTube Data API Discovery. 100% reliable.
        """
        if not podcast.channel_id:
            logger.error(f"Channel ID missing for {podcast.name}")
            return None
            
        logger.info(f"Official Discovery v6: Finding latest videos for {podcast.name}...")
        
        # Fetch and log channel info
        channel_info = youtube_service.get_channel_info(podcast.channel_id)
        if channel_info:
            logger.info(f"📊 Channel Info: {channel_info.name} | {channel_info.subscriber_count:,} subs | {channel_info.total_videos} videos | Country: {channel_info.country or 'N/A'}")
        
        videos = youtube_service.get_channel_latest_videos(podcast.channel_id, max_results=10)
        
        if not videos:
            logger.warning(f"Official API found no videos. Falling back to RSS Discovery...")
            return self._fetch_from_rss_fallback(podcast)
            
        for video in videos:
            logger.info(f"Checking video: {video['title']}")
            info = youtube_service.get_video_metadata(video['id'])
            if not info: continue
                
            duration = info.get('duration', 0)
            if duration > settings.MIN_EPISODE_DURATION:
                # Log extended metadata
                license_type = info.get('license', 'youtube')
                licensed_content = info.get('licensed_content', False)
                logger.info(f"✅ Found valid episode: {info['title']} ({duration}s)")
                logger.info(f"   📜 License: {license_type} | Content ID tracked: {licensed_content}")
                return info
            else:
                logger.info(f"⏭️ Skipping {info['title']} (Too short: {duration}s)")
        
        logger.error(f"No long-form episodes found among last 10 uploads for {podcast.name}")
        return None

    def _fetch_from_rss_fallback(self, podcast: Podcast) -> Optional[Dict]:
        """
        Fallback Discovery: uses yt-dlp to scrape the channel's /videos page.
        This works even without an API key and gives us duration.
        """
        logger.info(f"yt-dlp Channel Discovery for {podcast.name}...")
        try:
            url = f"https://www.youtube.com/channel/{podcast.channel_id}/videos"
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'playlist_items': '1-15',  # Check the latest 15 uploads
            }
            cookies_path = str(settings.BASE_DIR / "cookies.txt")
            if os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0:
                opts['cookiefile'] = cookies_path
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                entries = list(info.get('entries', []))
            
            logger.info(f"Found {len(entries)} videos on channel page")
            
            for entry in entries:
                vid_id = entry.get('id', '')
                title = entry.get('title', 'Unknown')
                duration = entry.get('duration', 0) or 0
                
                if duration > settings.MIN_EPISODE_DURATION:
                    logger.info(f"✅ Found valid episode: {title} ({duration}s)")
                    return {
                        "id": vid_id,
                        "title": title,
                        "description": entry.get('description', ''),
                        "duration": duration,
                        "thumbnail": entry.get('thumbnail', ''),
                        "channel_title": entry.get('channel', podcast.name),
                        "channel_id": podcast.channel_id,
                        "license": "youtube",
                        "licensed_content": False,
                        "content_rating": {},
                        "privacy_status": "public",
                    }
                else:
                    logger.info(f"⏭️ Skipping: {title} ({duration}s < {settings.MIN_EPISODE_DURATION}s)")
            
            logger.warning(f"No long-form episodes found in latest 15 uploads for {podcast.name}")
        except Exception as e:
            logger.error(f"yt-dlp channel discovery failed: {e}")
        return None

    def _download_via_cobalt(self, video_url: str, output_path: str, is_audio: bool = False, start_time: float = None, end_time: float = None) -> bool:
        """Downloads/Slices media using the Cobalt API (Primary Layer)."""
        logger.info(f"V6: Attempting download via Cobalt Bridge...")
        
        # Build quality preference for Cobalt
        quality = settings.VIDEO_QUALITY_PREFERENCE[0] if settings.VIDEO_QUALITY_PREFERENCE else "1080"
        
        for instance in self.cobalt_instances:
            try:
                payload = {
                    "url": video_url,
                    "downloadMode": "audio" if is_audio else "default",
                    "videoQuality": quality,
                    "audioFormat": "best",
                    "youtubeVideoCodec": "h264"
                }
                res = requests.post(instance, json=payload, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=40)
                logger.info(f"Cobalt Request to {instance}: Status {res.status_code}")
                
                if res.status_code != 200:
                    logger.warning(f"Cobalt {instance} returned {res.status_code}: {res.text[:100]}")
                    continue
                    
                data = res.json()
                status = data.get("status")
                
                if status == "error":
                    logger.warning(f"Cobalt Error: {data.get('text')}")
                    continue
                
                stream_url = data.get("url")
                if not stream_url:
                    logger.warning(f"Cobalt instance returned no URL.")
                    continue
                    
                logger.info(f"Cobalt Ready. Retrieving stream...")
                
                if start_time is not None and end_time is not None:
                    duration = end_time - start_time
                    cmd = [
                        "ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration),
                        "-i", stream_url,
                        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", output_path
                    ]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    r = requests.get(stream_url, stream=True, timeout=60)
                    r.raise_for_status()
                    with open(output_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            f.write(chunk)
                
                if os.path.exists(output_path):
                    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    logger.info(f"✅ Cobalt Success! ({file_size_mb:.1f} MB)")
                    return True
            except Exception as e:
                logger.warning(f"Cobalt Instance failed: {e}")
        return False

    def _download_via_rapidapi(self, video_url: str, output_path: str, is_audio: bool = False) -> bool:
        """The 'Nuclear Option': Reliable Proxy-Based Downloader."""
        if not settings.RAPID_API_KEY:
            return False
            
        logger.info("NUCLEAR OPTION: Attempting download via RapidAPI Proxy...")
        try:
            url = "https://youtube-download-video-and-audio-v2.p.rapidapi.com/v1/download"
            querystring = {"url": video_url}
            headers = {
                "X-RapidAPI-Key": settings.RAPID_API_KEY,
                "X-RapidAPI-Host": "youtube-download-video-and-audio-v2.p.rapidapi.com"
            }
            res = requests.get(url, headers=headers, params=querystring, timeout=30)
            res.raise_for_status()
            data = res.json()
            
            # This API format typically returns a list of streams
            streams = data.get("streams", [])
            target_stream = None
            if is_audio:
                target_stream = next((s for s in streams if s.get("type") == "audio"), None)
            else:
                # Try quality preferences in order
                for quality in settings.VIDEO_QUALITY_PREFERENCE:
                    target_stream = next((s for s in streams if s.get("type") == "video" and s.get("quality") == f"{quality}p"), None)
                    if target_stream:
                        break
                if not target_stream:
                    target_stream = next((s for s in streams if s.get("type") == "video"), None)
                
            if not target_stream or "url" not in target_stream:
                return False
                
            r = requests.get(target_stream["url"], stream=True, timeout=120)
            r.raise_for_status()
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024): f.write(chunk)
            return os.path.exists(output_path)
        except Exception as e:
            logger.warning(f"RapidAPI failed: {e}")
            return False

    def _normalize_audio(self, file_path: str) -> str:
        """Applies loudness normalization via ffmpeg loudnorm filter."""
        if not settings.AUDIO_NORMALIZE:
            return file_path
            
        normalized_path = file_path.replace(".m4a", "_norm.m4a").replace(".mp4", "_norm.mp4")
        try:
            cmd = [
                "ffmpeg", "-y", "-i", file_path,
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a", "aac", "-b:a", "192k",
                normalized_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(normalized_path):
                os.remove(file_path)
                os.rename(normalized_path, file_path)
                logger.info("🔊 Audio normalized successfully.")
        except Exception as e:
            logger.warning(f"Audio normalization failed (using original): {e}")
        return file_path

    def _get_yt_dlp_format_string(self, is_audio: bool = False) -> str:
        """Builds yt-dlp format string based on quality preferences.
        Uses progressive streams (video+audio combined) when ffmpeg is unavailable."""
        if is_audio:
            return 'bestaudio[ext=m4a]/bestaudio/best'
        
        format_parts = []
        if self.has_ffmpeg:
            # Separate streams + merge (highest quality, requires ffmpeg)
            for quality in settings.VIDEO_QUALITY_PREFERENCE:
                format_parts.append(f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]")
        # Progressive streams (video+audio combined, works without ffmpeg)
        for quality in settings.VIDEO_QUALITY_PREFERENCE:
            format_parts.append(f"best[height<={quality}][ext=mp4]")
        format_parts.append("best[ext=mp4]/best")
        return "/".join(format_parts)

    def download_audio(self, video_id: str) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_audio_{video_id}.m4a")
        if os.path.exists(output_path): os.remove(output_path)
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. Cobalt (Primary)
        if self._download_via_cobalt(url, output_path, is_audio=True):
            return self._normalize_audio(output_path)
        
        # 2. RapidAPI (The Nuclear Backup)
        if self._download_via_rapidapi(url, output_path, is_audio=True):
            return self._normalize_audio(output_path)
            
        # 3. yt-dlp (Fallback)
        logger.info("Layer 3 Fallback: yt-dlp")
        opts = self.base_opts.copy()
        opts.update({'format': self._get_yt_dlp_format_string(is_audio=True), 'outtmpl': output_path})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
            if os.path.exists(output_path):
                return self._normalize_audio(output_path)
        except Exception: pass
        
        # 4. pytubefix (Fallback)
        logger.info("Layer 4 Fallback: pytubefix")
        try:
            yt = YouTube(url)
            yt.streams.get_audio_only().download(output_path=str(settings.DATA_DIR), filename=f"temp_audio_{video_id}.m4a")
            if os.path.exists(output_path):
                return self._normalize_audio(output_path)
        except Exception: pass

        return None

    def download_video_segment(self, video_id: str, start_time: float, end_time: float) -> Optional[str]:
        output_path = str(settings.DATA_DIR / f"temp_segment_{video_id}.mp4")
        if os.path.exists(output_path): os.remove(output_path)
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. Cobalt (Primary — requires ffmpeg for segment slicing)
        if self.has_ffmpeg:
            if self._download_via_cobalt(url, output_path, is_audio=False, start_time=start_time, end_time=end_time): return output_path
        
        # 2. yt-dlp with SEPARATE video+audio download & merge (highest quality, requires ffmpeg)
        if self.has_ffmpeg:
            logger.info("Layer 2: yt-dlp separate streams + ffmpeg merge")
            if self._download_separate_merge(url, output_path, start_time, end_time):
                return output_path
        
        # 3. yt-dlp single-pass with sections (requires ffmpeg for section cutting)
        if self.has_ffmpeg:
            logger.info("Layer 3: yt-dlp sections download")
            opts = self.base_opts.copy()
            format_str = self._get_yt_dlp_format_string(is_audio=False)
            opts.update({
                'format': format_str,
                'outtmpl': output_path,
                'download_sections': f"*{start_time}-{end_time}",
                'force_keyframes_at_cuts': True
            })
            try:
                with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
                if os.path.exists(output_path): return output_path
            except Exception as e:
                logger.warning(f"yt-dlp sections failed: {e}")

        # 4. yt-dlp full download + slice (download full video, then trim via python)
        logger.info("Layer 4: yt-dlp full download + python trim")
        full_path = str(settings.DATA_DIR / f"temp_full_{video_id}.mp4")
        try:
            opts2 = self.base_opts.copy()
            opts2.update({
                'format': self._get_yt_dlp_format_string(is_audio=False),
                'outtmpl': full_path,
            })
            with yt_dlp.YoutubeDL(opts2) as ydl: ydl.download([url])
            if os.path.exists(full_path):
                # Trim using moviepy (no ffmpeg needed)
                from moviepy.editor import VideoFileClip
                clip = VideoFileClip(full_path)
                trimmed = clip.subclip(start_time, min(end_time, clip.duration))
                trimmed.write_videofile(output_path, codec='libx264', audio_codec='aac', preset='ultrafast', logger=None)
                clip.close()
                trimmed.close()
                if os.path.exists(full_path): os.remove(full_path)
                if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.warning(f"Full download + trim failed: {e}")
            if os.path.exists(full_path):
                try: os.remove(full_path)
                except: pass

        # 5. pytubefix progressive + moviepy trim (last resort)
        logger.info("Layer 5 Fallback: pytubefix progressive + moviepy trim")
        try:
            yt = YouTube(url)
            stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            if stream:
                pytube_path = str(settings.DATA_DIR / f"temp_pytube_{video_id}.mp4")
                stream.download(output_path=str(settings.DATA_DIR), filename=f"temp_pytube_{video_id}.mp4")
                if os.path.exists(pytube_path):
                    from moviepy.editor import VideoFileClip
                    clip = VideoFileClip(pytube_path)
                    trimmed = clip.subclip(start_time, min(end_time, clip.duration))
                    trimmed.write_videofile(output_path, codec='libx264', audio_codec='aac', preset='ultrafast', logger=None)
                    clip.close()
                    trimmed.close()
                    if os.path.exists(pytube_path): os.remove(pytube_path)
                    if os.path.exists(output_path): return output_path
        except Exception as e:
            logger.warning(f"pytubefix + moviepy trim failed: {e}")
        
        return None

    def _download_separate_merge(self, url: str, output_path: str, start_time: float, end_time: float) -> bool:
        """
        Downloads best video + best audio as SEPARATE streams, then merges with ffmpeg.
        This produces the highest quality output (avoids progressive stream quality limits).
        """
        video_tmp = output_path.replace(".mp4", "_v.mp4")
        audio_tmp = output_path.replace(".mp4", "_a.m4a")
        
        try:
            # Download best video stream
            for quality in settings.VIDEO_QUALITY_PREFERENCE:
                v_opts = self.base_opts.copy()
                v_opts.update({
                    'format': f'bestvideo[height<={quality}][ext=mp4]/bestvideo[ext=mp4]',
                    'outtmpl': video_tmp,
                    'download_sections': f"*{start_time}-{end_time}",
                    'force_keyframes_at_cuts': True
                })
                try:
                    with yt_dlp.YoutubeDL(v_opts) as ydl:
                        ydl.download([url])
                    if os.path.exists(video_tmp):
                        logger.info(f"🎬 Video stream downloaded ({quality}p)")
                        break
                except Exception:
                    continue
            
            if not os.path.exists(video_tmp):
                return False
            
            # Download best audio stream
            a_opts = self.base_opts.copy()
            a_opts.update({
                'format': 'bestaudio[ext=m4a]/bestaudio',
                'outtmpl': audio_tmp,
                'download_sections': f"*{start_time}-{end_time}",
                'force_keyframes_at_cuts': True
            })
            with yt_dlp.YoutubeDL(a_opts) as ydl:
                ydl.download([url])
            
            if not os.path.exists(audio_tmp):
                # If audio download failed, just use video-only
                os.rename(video_tmp, output_path)
                return True
            
            # Merge video + audio via ffmpeg
            logger.info("🔀 Merging separate video + audio streams...")
            merge_cmd = [
                "ffmpeg", "-y",
                "-i", video_tmp,
                "-i", audio_tmp,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                output_path
            ]
            # Add audio normalization if enabled
            if settings.AUDIO_NORMALIZE:
                merge_cmd = [
                    "ffmpeg", "-y",
                    "-i", video_tmp,
                    "-i", audio_tmp,
                    "-c:v", "copy",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    output_path
                ]
            
            subprocess.run(merge_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Cleanup temp files
            for tmp in [video_tmp, audio_tmp]:
                if os.path.exists(tmp):
                    os.remove(tmp)
            
            if os.path.exists(output_path):
                file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                logger.info(f"✅ Merged video ready ({file_size_mb:.1f} MB)")
                return True
            
        except Exception as e:
            logger.warning(f"Separate merge failed: {e}")
            # Cleanup temp files
            for tmp in [video_tmp, audio_tmp]:
                if os.path.exists(tmp):
                    os.remove(tmp)
        
        return False

downloader = DownloadService()
