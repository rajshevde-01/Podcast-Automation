import os
import sys
import time
import requests
import subprocess
from loguru import logger
from .config import settings
from .database import db_manager
from .services.downloader import downloader
from .services.processor import processor
from .services.llm_curator import curator
from .services.video_engine import video_service
from .services.thumbnail_engine import thumbnail_service
from .services.youtube import youtube_service
from .services.copyright_checker import checker

class AutomationPipeline:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        # Set up logging
        log_dir = settings.BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "pipeline_{time}.log"
        logger.add(log_file, rotation="10 MB", retention="10 days", level="INFO")
        
        # Check for ffmpeg
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            logger.info("✅ ffmpeg found and ready.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("⚠️ ffmpeg not found in PATH. Video slicing and rendering may fail.")

    def _send_discord_notification(self, title: str, url: str):
        if not settings.DISCORD_WEBHOOK_URL:
            return
        data = {"content": f"🚀 **New Podcast Short!**\n*{title}*\nWatch: {url}"}
        try:
            requests.post(settings.DISCORD_WEBHOOK_URL, json=data)
            logger.info("Discord notification sent.")
        except Exception as e:
            logger.error(f"Discord Webhook Failed: {e}")

    def run(self):
        logger.info("🚀 Starting Podcast Shorts Automation Pipeline v6")
        logger.info(f"🛡️ Copyright risk threshold: {settings.COPYRIGHT_RISK_THRESHOLD}")
        logger.info(f"🎬 Video quality preference: {settings.VIDEO_QUALITY_PREFERENCE}")
        logger.info(f"🔊 Audio normalization: {'ON' if settings.AUDIO_NORMALIZE else 'OFF'}")
        
        try:
            # Try up to 5 different podcasts in case one fails
            podcast = None
            episode_meta = None
            video_id = None
            title = None
            audio_path = None
            
            for attempt in range(5):
                podcast = downloader.get_random_podcast()
                if not podcast:
                    logger.error("❌ No podcasts found in list (or all filtered by copyright).")
                    sys.exit(1)

                logger.info(f"🔄 Attempt {attempt + 1}: Selected Podcast: {podcast.name}")
                logger.info(f"   🛡️ Risk: {podcast.copyright_risk} | Policy: {podcast.license_policy or 'N/A'}")
                
                # Cache channel info in DB
                if podcast.channel_id:
                    channel_info = youtube_service.get_channel_info(podcast.channel_id)
                    if channel_info:
                        db_manager.save_channel_info(
                            channel_id=podcast.channel_id,
                            name=channel_info.name,
                            subscriber_count=channel_info.subscriber_count,
                            total_videos=channel_info.total_videos,
                            country=channel_info.country,
                            copyright_risk=podcast.copyright_risk,
                            license_policy=podcast.license_policy,
                        )
                
                episode_meta = downloader.fetch_latest_episode(podcast)
                if not episode_meta:
                    logger.warning(f"⚠️ Could not fetch episode for {podcast.name}. Trying another channel...")
                    continue

                video_id = episode_meta['id']
                title = episode_meta['title']

                if db_manager.is_episode_processed(video_id):
                    logger.info(f"Episode {video_id} already processed. Skipping to next podcast.")
                    continue

                # Copyright safety check on the specific video
                logger.info(f"🛡️ Running copyright safety check on video: {video_id}")
                is_safe = checker.is_safe_to_clip(video_id, podcast.copyright_risk)
                if not is_safe:
                    logger.warning(f"⚠️ Video {video_id} failed copyright safety check. Trying another...")
                    continue

                # 2. Extract Highlight
                audio_path = downloader.download_audio(video_id)
                if not audio_path:
                    logger.error("❌ FAILED: Could not download audio for this episode. Trying another...")
                    continue
                    
                # If we got audio successfully, break out of retry loop and proceed
                break
                
            else:
                # If the loop finished without breaking, ALL 5 attempts failed
                logger.error("❌ FAILED: All 5 podcast attempts failed. Check logs.")
                sys.exit(1)

            # Determine video type based on the day of the year (alternating)
            from datetime import datetime
            day_of_year = datetime.now().timetuple().tm_yday
            video_type = "long" if day_of_year % 2 == 0 else "short"
            logger.info(f"📅 Today is day {day_of_year}. Running in {video_type.upper()} mode.")

            transcript = processor.transcribe(audio_path)
            highlight = curator.find_best_highlight(transcript, video_type=video_type)
            
            if not highlight:
                logger.error(f"❌ FAILED: Could not find a viral highlight for {video_type} format.")
                sys.exit(1)

            # 3. Process Video
            logger.info(f"Targeting highlight: {highlight.start_time}s - {highlight.end_time}s")
            segment_path = downloader.download_video_segment(video_id, highlight.start_time, highlight.end_time)
            if not segment_path:
                logger.error("❌ FAILED: Could not download video segment.")
                sys.exit(1)

            # Get word-level timestamps for kinetic text
            word_segments = processor.transcribe(segment_path, word_timestamps=True)
            words = []
            for seg in word_segments:
                if "words" in seg:
                    words.extend(seg["words"])

            # Build credit text for attribution
            credit_text = f"Clip from: {podcast.name}"
            if episode_meta.get('channel_title'):
                credit_text = f"Clip from: {episode_meta['channel_title']} — {title}"

            final_video_path = video_service.create_video(
                segment_path, 
                highlight.title, 
                words, 
                b_roll_keyword=highlight.b_roll_keyword,
                credit_text=credit_text,
                video_type=video_type,
            )

            # 4. Create Thumbnail
            thumbnail_path = thumbnail_service.create_thumbnail(highlight.title, video_id)

            # 5. Upload to YouTube
            if self.dry_run:
                logger.info("Dry run enabled. Skipping upload.")
                logger.info(f"Final video saved at: {final_video_path}")
                return

            description = f"🔥 {highlight.title}\n\n"
            description += f"📎 Credit: {podcast.name} — {title}\n"
            description += f"🛡️ Copyright Risk: {podcast.copyright_risk}\n\n"
            
            if video_type == "short":
                description += "Subscribe for daily podcast bytes!\n"
            else:
                description += "Subscribe for daily deep-dive podcast highlights!\n"
                
            description += " ".join([f"#{t.replace(' ', '').replace('#', '')}" for t in highlight.hashtags])
            
            tags = highlight.hashtags + [podcast.name, "podcast", "highlight"]
            if video_type == "short":
                tags.append("shorts")
            
            # Get license info for logging
            license_type = episode_meta.get('license', 'youtube')
            
            final_upload_title = highlight.title
            if video_type == "short":
                final_upload_title += " #shorts"
            
            upload_url = youtube_service.upload_video(
                final_video_path,
                final_upload_title,
                description,
                tags,
                thumbnail_path
            )

            if upload_url:
                db_manager.log_episode(
                    video_id, podcast.name, title,
                    license_type=license_type,
                    copyright_risk=podcast.copyright_risk
                )
                short_id = db_manager.log_short(video_id, highlight.start_time, highlight.end_time, highlight.title)
                db_manager.mark_short_uploaded(short_id, upload_url)
                self._send_discord_notification(highlight.title, upload_url)
                logger.info(f"✅ Pipeline Completed Successfully! {upload_url}")
            else:
                logger.error("❌ FAILED: YouTube upload returned no URL. Check OAuth token!")
                sys.exit(1)
            
            # 6. Cleanup
            for f in [audio_path, segment_path, final_video_path, thumbnail_path]:
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception as e:
                        logger.warning(f"Cleanup failed for {f}: {e}")

            logger.info("🏁 Pipeline v6 finished processing.")

        except SystemExit:
            raise  # Re-raise sys.exit calls
        except Exception as e:
            logger.exception(f"PIPELINE CRITICAL ERROR: {e}")
            sys.exit(1)

if __name__ == "__main__":
    pipeline = AutomationPipeline(dry_run=True)
    pipeline.run()
