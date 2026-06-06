import os
import sys
import uuid
import json
import shutil
import argparse
from pathlib import Path
from loguru import logger

# Set up environment variables inside python for Node.js and ImageMagick
def setup_environment():
    path = os.environ.get("PATH", "")
    new_paths = []
    
    # Prepend D:\ for Node
    if "D:\\" not in path and "d:\\" not in path.lower():
        new_paths.append("D:\\")
        
    # Prepend WinGet Links path
    winget_links = r"C:\Users\rajsh\AppData\Local\Microsoft\WinGet\Links"
    if winget_links not in path:
        new_paths.append(winget_links)
        
    # Add new paths to env PATH
    if new_paths:
        os.environ["PATH"] = ";".join(new_paths) + ";" + path
        
    # Dynamically search and add Gyan.FFmpeg bin directory to PATH
    try:
        user_profile = os.environ.get("USERPROFILE", "C:\\Users\\rajsh")
        winget_pkg_dir = Path(user_profile) / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        if winget_pkg_dir.exists():
            for p in winget_pkg_dir.glob("**/ffmpeg.exe"):
                ffmpeg_dir = str(p.parent)
                if ffmpeg_dir not in os.environ["PATH"]:
                    os.environ["PATH"] = ffmpeg_dir + ";" + os.environ["PATH"]
                    logger.info(f"Dynamically added physical ffmpeg binary path to PATH: {ffmpeg_dir}")
                    break
    except Exception as e:
        logger.warning(f"Failed to dynamically locate ffmpeg in packages: {e}")
        
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
    logger.info("Environment paths configuration complete.")

setup_environment()

# Now import project modules
from src.podcast_automation.config import settings
from src.podcast_automation.database import db_manager
from src.podcast_automation.services.downloader import downloader
from src.podcast_automation.services.processor import processor
from src.podcast_automation.services.llm_curator import curator
from src.podcast_automation.services.video_engine import video_service
from src.podcast_automation.services.thumbnail_engine import thumbnail_service

QUEUE_DIR = settings.OUTPUT_DIR / "scheduled_queue"

def get_existing_queue_episode_ids() -> set:
    """Scan queue directory to see which episode IDs are already queued."""
    queued_ids = set()
    if not QUEUE_DIR.exists():
        return queued_ids
    for item in QUEUE_DIR.iterdir():
        if item.is_dir():
            meta_file = item / "metadata.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if "episode_id" in meta:
                            queued_ids.add(meta["episode_id"])
                except Exception:
                    pass
    return queued_ids

def count_queue_items() -> int:
    """Count how many short packages are in the queue."""
    if not QUEUE_DIR.exists():
        return 0
    return sum(1 for item in QUEUE_DIR.iterdir() if item.is_dir() and (item / "metadata.json").exists())

def pick_next_episode(processed_and_queued_ids: set):
    """Pick an unprocessed and un-queued episode systematically."""
    if not os.path.exists(settings.PODCASTS_LIST_FILE):
        logger.error(f"Podcasts list file not found: {settings.PODCASTS_LIST_FILE}")
        return None
    with open(settings.PODCASTS_LIST_FILE, 'r') as f:
        data = json.load(f)
    podcasts_data = data.get("india_top_10", []) + data.get("world_top_20", [])
    
    from src.podcast_automation.models import Podcast
    podcasts = [Podcast(**choice) for choice in podcasts_data]
    import random
    random.shuffle(podcasts)
    
    logger.info(f"Checking {len(podcasts)} podcasts systematically for unprocessed episodes...")
    for podcast in podcasts:
        if not podcast.channel_id:
            continue
            
        logger.info(f"🔍 Checking Podcast: {podcast.name}")
        try:
            videos = downloader.fetch_latest_episode(podcast) # Fetches latest valid
            if not videos:
                continue
                
            video_id = videos["id"]
            title = videos["title"]
            
            if video_id in processed_and_queued_ids or db_manager.is_episode_processed(video_id):
                logger.info(f"Episode {video_id} ('{title}') is already processed or queued. Skipping.")
                continue
                
            return podcast, videos
        except Exception as e:
            logger.warning(f"Error fetching latest episode for {podcast.name}: {e}")
            
    return None

def generate_shorts(target_count: int, highlights_per_episode: int):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    current_queue_count = count_queue_items()
    logger.info(f"Current items in queue: {current_queue_count}. Target: {target_count}.")
    
    if current_queue_count >= target_count:
        logger.info("Queue is already full!")
        return

    processed_and_queued_ids = get_existing_queue_episode_ids()
    
    needed = target_count - current_queue_count
    generated_this_run = 0
    
    logger.info(f"Starting batch generation to create {needed} shorts.")
    
    while generated_this_run < needed:
        logger.info(f"--- Progress: {generated_this_run}/{needed} generated this run ---")
        
        # Pick a podcast & episode
        pick = pick_next_episode(processed_and_queued_ids)
        if not pick:
            logger.error("Could not find any more unprocessed episodes. Exiting loop.")
            break
            
        podcast, episode_meta = pick
        video_id = episode_meta["id"]
        title = episode_meta["title"]
        podcast_name = podcast.name
        
        processed_and_queued_ids.add(video_id)
        
        logger.info(f"🎙️ Selected: {podcast_name} - {title} (ID: {video_id})")
        
        # Download audio
        audio_path = downloader.download_audio(video_id, podcast=podcast)
        if not audio_path or not os.path.exists(audio_path):
            logger.error(f"Failed to download audio for episode {video_id}")
            continue
            
        try:
            # Transcribe full episode audio
            logger.info("Transcribing audio...")
            transcript = processor.transcribe(audio_path)
            
            # Detect guest/topic
            meta = curator.detect_guest_and_topic(transcript)
            guest_name = meta.get("guest_name")
            topic = meta.get("topic")
            
            # Extract highlights
            logger.info("Extracting viral highlights via LLM...")
            top_clips = db_manager.get_top_performing_clips(limit=5)
            highlights = curator.find_best_highlights(
                transcript,
                top_performing_clips=top_clips if top_clips else None,
                n=highlights_per_episode
            )
            
            if not highlights:
                logger.warning(f"No viral highlights found for {title}. Skipping.")
                continue
                
            logger.info(f"Found {len(highlights)} highlights. Processing them...")
            
            for index, highlight in enumerate(highlights):
                if generated_this_run >= needed:
                    logger.info("Target count reached during highlight processing.")
                    break
                    
                # Inherit guest metadata if needed
                if not highlight.guest_name and guest_name:
                    highlight.guest_name = guest_name
                if not highlight.topic and topic:
                    highlight.topic = topic
                    
                logger.info(f"Generating Short {index+1}/{len(highlights)}: '{highlight.title}' ({highlight.start_time}s - {highlight.end_time}s)")
                
                # Download video segment
                segment_path = downloader.download_video_segment(
                    video_id, highlight.start_time, highlight.end_time
                )
                if not segment_path or not os.path.exists(segment_path):
                    logger.error("Failed to download video segment.")
                    continue
                    
                try:
                    # Get word timestamps
                    word_segments = processor.transcribe(segment_path, word_timestamps=True)
                    words = []
                    for seg in word_segments:
                        if "words" in seg:
                            words.extend(seg["words"])
                            
                    # Render video
                    final_video_path = video_service.create_video(
                        segment_path,
                        highlight.title,
                        words,
                        b_roll_keyword=highlight.b_roll_keyword
                    )
                    
                    if not final_video_path or not os.path.exists(final_video_path):
                        logger.error("Failed to render video short.")
                        continue
                        
                    # Extract face frame + create thumbnail
                    face_frame = video_service.extract_best_face_frame(segment_path)
                    thumbnail_path = thumbnail_service.create_thumbnail(
                        highlight.title,
                        video_id,
                        face_frame_bgr=face_frame,
                        channel_id=podcast.channel_id
                    )
                    
                    if not thumbnail_path or not os.path.exists(thumbnail_path):
                        logger.error("Failed to create thumbnail.")
                        continue
                        
                    # Create queue package directory
                    package_id = f"{video_id}_{int(highlight.start_time)}"
                    package_dir = QUEUE_DIR / package_id
                    package_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Copy video and thumbnail to package directory
                    queue_video_path = package_dir / "short.mp4"
                    queue_thumb_path = package_dir / "thumbnail.jpg"
                    
                    shutil.copy2(final_video_path, queue_video_path)
                    shutil.copy2(thumbnail_path, queue_thumb_path)
                    
                    # Build descriptions & tags
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
                        
                    # Write metadata.json
                    metadata = {
                        "episode_id": video_id,
                        "podcast_name": podcast_name,
                        "original_title": title,
                        "title": highlight.title + " #shorts",
                        "description": description,
                        "tags": tags,
                        "start_time": highlight.start_time,
                        "end_time": highlight.end_time,
                        "viral_score": highlight.viral_score
                    }
                    
                    with open(package_dir / "metadata.json", "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=4)
                        
                    logger.info(f"✅ Packaged successfully in: {package_dir}")
                    generated_this_run += 1
                    
                    # Log the episode to database so we don't pick it in future pipeline runs
                    db_manager.log_episode(video_id, podcast_name, title)
                    
                except Exception as e:
                    logger.exception(f"Error processing highlight: {e}")
                finally:
                    # Clean up segment and output files
                    if segment_path and os.path.exists(segment_path):
                        os.remove(segment_path)
                    if 'final_video_path' in locals() and final_video_path and os.path.exists(final_video_path):
                        os.remove(final_video_path)
                    if 'thumbnail_path' in locals() and thumbnail_path and os.path.exists(thumbnail_path):
                        os.remove(thumbnail_path)
                        
        except Exception as e:
            logger.exception(f"Error processing episode: {e}")
        finally:
            # Clean up the downloaded full audio file
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
                
    logger.info(f"Batch generation finished! Created {generated_this_run} new shorts. Total queue count: {count_queue_items()}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch generate podcast shorts into a local queue folder.")
    parser.add_argument("--count", type=int, default=50, help="Target total number of videos in the queue.")
    parser.add_argument("--highlights-per-episode", type=int, default=3, help="How many highlights to extract per episode.")
    args = parser.parse_args()
    
    generate_shorts(args.count, args.highlights_per_episode)
