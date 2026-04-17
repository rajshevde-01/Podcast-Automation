import os
import sys
import time
import uuid
import json
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
from .services.notifications import notification_service

class AutomationPipeline:
    def __init__(self, dry_run: bool = False, run_id: str = None):
        self.dry_run = dry_run
        # Stable run_id lets a re-run resume where it left off
        self.run_id = run_id or os.environ.get("GITHUB_RUN_ID") or str(uuid.uuid4())[:8]

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

    # ------------------------------------------------------------------
    # Secret validation
    # ------------------------------------------------------------------

    def _validate_secrets(self):
        """
        Fail fast if required secrets are missing before any expensive work starts.
        Warns (but does not fail) for optional secrets that improve reliability.
        """
        missing_upload = [
            name
            for name, val in [
                ("YOUTUBE_CLIENT_ID", settings.YOUTUBE_CLIENT_ID),
                ("YOUTUBE_CLIENT_SECRET", settings.YOUTUBE_CLIENT_SECRET),
                ("YOUTUBE_REFRESH_TOKEN", settings.YOUTUBE_REFRESH_TOKEN),
            ]
            if not val
        ]
        if missing_upload and not self.dry_run:
            logger.error(
                f"❌ MISSING REQUIRED UPLOAD SECRETS: {', '.join(missing_upload)}. "
                "Set these as GitHub Actions secrets. The pipeline cannot upload "
                "without YouTube OAuth credentials."
            )
            sys.exit(1)

        if not settings.RAPID_API_KEY:
            logger.warning(
                "⚠️  RAPID_API_KEY is not set. The RapidAPI download layer will be "
                "skipped. Podcasts without an 'rss_feed' entry will rely on yt-dlp, "
                "which may fail with YouTube bot-detection in CI. "
                "Set RAPID_API_KEY in GitHub Actions secrets for more reliable downloads."
            )

        if not settings.YOUTUBE_API_KEY:
            logger.warning(
                "⚠️  YOUTUBE_API_KEY is not set. Episode discovery will use the "
                "YouTube channel RSS fallback, which may be slower."
            )

        # Log the active download strategy so it's visible in CI logs
        if settings.RAPID_API_KEY:
            logger.info(
                "📡 Download strategy: RSS-first (when podcast.rss_feed is configured), "
                "then RapidAPI, then yt-dlp."
            )
        else:
            logger.info(
                "📡 Download strategy: RSS-first (when podcast.rss_feed is configured), "
                "then yt-dlp (RapidAPI not available)."
            )

        logger.info("✅ Secret validation complete.")

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _pick_episode(self):
        """Try up to 5 podcasts until we get a valid un-processed episode + audio."""
        for attempt in range(5):
            podcast = downloader.get_random_podcast()
            if not podcast:
                logger.error("❌ No podcasts found in list.")
                sys.exit(1)

            logger.info(f"🔄 Attempt {attempt + 1}: Selected Podcast: {podcast.name}")

            episode_meta = downloader.fetch_latest_episode(podcast)
            if not episode_meta:
                logger.warning(f"⚠️ Could not fetch episode for {podcast.name}. Trying another…")
                continue

            video_id = episode_meta["id"]
            title = episode_meta["title"]

            if db_manager.is_episode_processed(video_id):
                logger.info(f"Episode {video_id} already processed. Trying another podcast.")
                continue

            audio_path = downloader.download_audio(video_id, podcast=podcast)
            if not audio_path:
                logger.error("❌ Could not download audio. Trying another…")
                continue

            return podcast, episode_meta, video_id, title, audio_path

        logger.error("❌ FAILED: All 5 podcast attempts failed. Check logs.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self):
        logger.info(f"🚀 Starting Podcast Shorts Automation Pipeline [run_id={self.run_id}]")
        self._validate_secrets()

        try:
            # ── Step 1: Check for resumable state ────────────────────────────
            state = db_manager.get_pipeline_state(self.run_id)
            if state and state.get("stage") not in (None, "started"):
                logger.info(f"♻️  Resuming pipeline from stage: {state['stage']}")
                podcast_obj   = None   # not persisted; only needed for channel_id
                video_id      = state.get("episode_id", "")
                title         = ""    # not critical after upload; used in description only
                audio_path    = state.get("audio_path")
                segment_path  = state.get("segment_path")
                final_video_path  = state.get("final_video_path")
                thumbnail_path    = state.get("thumbnail_path")
                highlight_json    = state.get("highlight_json")
                highlight = None
                if highlight_json:
                    from .models import Highlight
                    try:
                        highlight = Highlight(**json.loads(highlight_json))
                    except Exception:
                        pass
                podcast_name = state.get("podcast_name", "Unknown Podcast")
            else:
                # ── Step 2: Pick episode + download audio ─────────────────────
                db_manager.save_pipeline_state(self.run_id, "started")
                podcast_obj, episode_meta, video_id, title, audio_path = self._pick_episode()
                podcast_name = podcast_obj.name
                db_manager.save_pipeline_state(
                    self.run_id, "audio_downloaded",
                    episode_id=video_id, podcast_name=podcast_name,
                    audio_path=audio_path
                )
                segment_path = None
                final_video_path = None
                thumbnail_path = None
                highlight = None

            # ── Step 3: Transcribe + highlight extraction ─────────────────────
            if highlight is None:
                transcript = processor.transcribe(audio_path)

                # Historical virality feedback loop
                top_clips = db_manager.get_top_performing_clips(limit=5)

                # Guest/topic detection (runs fast, uses only first 3 min)
                meta = curator.detect_guest_and_topic(transcript)
                guest_name = meta.get("guest_name")
                topic = meta.get("topic")
                if guest_name:
                    logger.info(f"🎙️  Detected guest: {guest_name} | topic: {topic}")

                highlights = curator.find_best_highlights(
                    transcript,
                    top_performing_clips=top_clips if top_clips else None,
                    n=settings.MAX_HIGHLIGHTS_PER_RUN,
                )

                if not highlights:
                    logger.error("❌ FAILED: Could not find any viral highlights.")
                    sys.exit(1)

                highlight = highlights[0]
                logger.info(
                    f"🏆 Best highlight: '{highlight.title}' "
                    f"(score={highlight.viral_score:.1f}, "
                    f"{highlight.start_time:.0f}s–{highlight.end_time:.0f}s)"
                )
                if len(highlights) > 1:
                    for alt in highlights[1:]:
                        logger.info(
                            f"   Alt highlight: '{alt.title}' (score={alt.viral_score:.1f})"
                        )

                # Inherit guest metadata from detection if LLM didn't provide it
                if not highlight.guest_name and guest_name:
                    highlight.guest_name = guest_name
                if not highlight.topic and topic:
                    highlight.topic = topic

                db_manager.save_pipeline_state(
                    self.run_id, "highlights_found",
                    highlight_json=highlight.model_dump_json()
                )

            # ── Step 4: Download video segment ────────────────────────────────
            if not segment_path or not os.path.exists(segment_path):
                logger.info(f"Targeting highlight: {highlight.start_time}s - {highlight.end_time}s")
                segment_path = downloader.download_video_segment(
                    video_id, highlight.start_time, highlight.end_time
                )
                if not segment_path:
                    logger.error("❌ FAILED: Could not download video segment.")
                    sys.exit(1)
                db_manager.save_pipeline_state(
                    self.run_id, "video_downloaded", segment_path=segment_path
                )

            # ── Step 5: Word-level transcription for karaoke subtitles ────────
            word_segments = processor.transcribe(segment_path, word_timestamps=True)
            words = []
            for seg in word_segments:
                if "words" in seg:
                    words.extend(seg["words"])

            # ── Step 6: Render video ───────────────────────────────────────────
            if not final_video_path or not os.path.exists(final_video_path):
                final_video_path = video_service.create_video(
                    segment_path,
                    highlight.title,
                    words,
                    b_roll_keyword=highlight.b_roll_keyword,
                )
                db_manager.save_pipeline_state(
                    self.run_id, "video_rendered", final_video_path=final_video_path
                )

            # ── Step 7: Create thumbnail (with face frame + logo) ─────────────
            if not thumbnail_path or not os.path.exists(thumbnail_path):
                # Try to extract the best face frame from the rendered segment
                face_frame = video_service.extract_best_face_frame(segment_path)
                thumbnail_path = thumbnail_service.create_thumbnail(
                    highlight.title,
                    video_id,
                    face_frame_bgr=face_frame,
                    channel_id=getattr(podcast_obj, "channel_id", None) if podcast_obj else None,
                )
                db_manager.save_pipeline_state(
                    self.run_id, "thumbnail_created", thumbnail_path=thumbnail_path
                )

            # ── Step 8: Upload ─────────────────────────────────────────────────
            if self.dry_run:
                logger.info("Dry run enabled. Skipping upload.")
                logger.info(f"Final video saved at: {final_video_path}")
                db_manager.delete_pipeline_state(self.run_id)
                return

            # Build rich description including guest and topic
            guest_credit = f" ft. {highlight.guest_name}" if highlight.guest_name else ""
            topic_line = f"Topic: {highlight.topic}\n\n" if highlight.topic else ""
            description = (
                f"🔥 {highlight.title}\n\n"
                f"{topic_line}"
                f"Credit: {podcast_name}{guest_credit} — {title}\n\n"
                "Subscribe for daily podcast bytes!\n"
            )
            description += " ".join(
                f"#{t.replace(' ', '').replace('#', '')}" for t in highlight.hashtags
            )

            tags = highlight.hashtags + [podcast_name, "shorts", "podcast"]
            if highlight.guest_name:
                tags.append(highlight.guest_name)
            if highlight.topic:
                tags.append(highlight.topic)

            upload_url = youtube_service.upload_video(
                final_video_path,
                highlight.title + " #shorts",
                description,
                tags,
                thumbnail_path,
            )

            if upload_url:
                db_manager.log_episode(video_id, podcast_name, title)
                short_id = db_manager.log_short(
                    video_id,
                    highlight.start_time,
                    highlight.end_time,
                    highlight.title,
                    viral_score=highlight.viral_score,
                )
                db_manager.mark_short_uploaded(short_id, upload_url)

                # Broadcast to all configured notification channels
                notification_service.broadcast(
                    title=highlight.title,
                    url=upload_url,
                    thumbnail_path=thumbnail_path,
                )

                logger.info(f"✅ Pipeline Completed Successfully! {upload_url}")
                db_manager.delete_pipeline_state(self.run_id)
            else:
                logger.error("❌ FAILED: YouTube upload returned no URL. Check OAuth token!")
                sys.exit(1)

            # ── Step 9: Cleanup ────────────────────────────────────────────────
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
