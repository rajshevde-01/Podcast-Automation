import os
import sys
import time
import requests
from loguru import logger
from .config import settings
from .database import db_manager
from .services.downloader import downloader
from .services.processor import processor
from .services.llm_curator import curator
from .services.video_engine import video_service
from .services.thumbnail_engine import thumbnail_service
from .services.youtube import youtube_service

class AutomationPipeline:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        # Set up logging
        log_file = settings.BASE_DIR / "logs" / "pipeline_{time}.log"
        logger.add(log_file, rotation="10 MB", retention="10 days", level="INFO")

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
        logger.info("🚀 Starting Podcast Shorts Automation Pipeline")
        
        try:
            # Try up to 5 different podcasts in case one fails
            for attempt in range(5):
                podcast = downloader.get_random_podcast()
                if not podcast:
                    logger.error("❌ No podcasts found in list.")
                    sys.exit(1)

                logger.info(f"🔄 Attempt {attempt + 1}: Selected Podcast: {podcast.name}")
                
                episode_meta = downloader.fetch_latest_episode(podcast)
                if not episode_meta:
                    logger.warning(f"⚠️ Could not fetch episode for {podcast.name}. Trying another channel...")
                    continue

                video_id = episode_meta['id']
                title = episode_meta['title']

                if db_manager.is_episode_processed(video_id):
                    logger.info(f"Episode {video_id} already processed. Skipping to next podcast.")
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

            transcript = processor.transcribe(audio_path)
            highlight = curator.find_best_highlight(transcript)
            
            if not highlight:
                logger.error("❌ FAILED: Could not find a viral highlight.")
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

            final_video_path = video_service.create_video(
                segment_path, 
                highlight.title, 
                words, 
                b_roll_keyword=highlight.b_roll_keyword
            )

            # 4. Create Thumbnail
            thumbnail_path = thumbnail_service.create_thumbnail(highlight.title, video_id)

            # 5. Upload to YouTube
            if self.dry_run:
                logger.info("Dry run enabled. Skipping upload.")
                logger.info(f"Final video saved at: {final_video_path}")
                return

            description = f"🔥 {highlight.title}\n\nCredit: {podcast.name} - {title}\n\nSubscribe for daily podcast bytes!\n"
            description += " ".join([f"#{t.replace(' ', '').replace('#', '')}" for t in highlight.hashtags])
            
            tags = highlight.hashtags + [podcast.name, "shorts", "podcast"]
            
            upload_url = youtube_service.upload_video(
                final_video_path,
                highlight.title + " #shorts",
                description,
                tags,
                thumbnail_path
            )

            if upload_url:
                db_manager.log_episode(video_id, podcast.name, title)
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

            logger.info("🏁 Pipeline finished processing.")

        except SystemExit:
            raise  # Re-raise sys.exit calls
        except Exception as e:
            logger.exception(f"PIPELINE CRITICAL ERROR: {e}")
            sys.exit(1)

if __name__ == "__main__":
    pipeline = AutomationPipeline(dry_run=True)
    pipeline.run()
