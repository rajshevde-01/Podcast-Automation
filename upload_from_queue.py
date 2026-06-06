import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from typing import Optional
from loguru import logger

# Set up environment variables inside python
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
                    break
    except Exception:
        pass
        
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

setup_environment()

# Now import project modules
from src.podcast_automation.config import settings
from src.podcast_automation.database import db_manager
from src.podcast_automation.services.youtube import youtube_service
from src.podcast_automation.services.notifications import notification_service

QUEUE_DIR = settings.OUTPUT_DIR / "scheduled_queue"

def get_oldest_queue_package() -> Optional[Path]:
    """Find the oldest subdirectory in QUEUE_DIR containing metadata.json."""
    if not QUEUE_DIR.exists():
        return None
        
    packages = []
    for item in QUEUE_DIR.iterdir():
        if item.is_dir() and (item / "metadata.json").exists():
            # Get folder creation/modification time
            mtime = item.stat().st_mtime
            packages.append((mtime, item))
            
    if not packages:
        return None
        
    # Sort by modification time (oldest first)
    packages.sort(key=lambda x: x[0])
    return packages[0][1]

def upload_next(dry_run: bool = False) -> int:
    package_dir = get_oldest_queue_package()
    if not package_dir:
        logger.warning("⚠️ No scheduled videos found in queue directory!")
        return 10
        
    logger.info(f"📂 Selected package for upload: {package_dir.name}")
    
    meta_path = package_dir / "metadata.json"
    video_path = package_dir / "short.mp4"
    thumb_path = package_dir / "thumbnail.jpg"
    
    if not video_path.exists():
        logger.error(f"❌ Video file missing in package: {video_path}")
        return 1
        
    # Load metadata
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        logger.error(f"❌ Failed to parse metadata.json: {e}")
        return 1
        
    title = meta.get("title")
    description = meta.get("description")
    tags = meta.get("tags", [])
    episode_id = meta.get("episode_id")
    podcast_name = meta.get("podcast_name")
    original_title = meta.get("original_title")
    start_time = meta.get("start_time", 0.0)
    end_time = meta.get("end_time", 0.0)
    viral_score = meta.get("viral_score", 0.0)
    
    logger.info(f"🎥 Title: {title}")
    logger.info(f"🎙️ Podcast: {podcast_name} | Episode ID: {episode_id}")
    
    if dry_run:
        logger.info(f"[DRY RUN] Would upload {video_path} to YouTube.")
        logger.info(f"[DRY RUN] Title: {title}")
        logger.info(f"[DRY RUN] Tags: {tags}")
        logger.info(f"[DRY RUN] Thumbnail: {thumb_path if thumb_path.exists() else 'None'}")
        return 0
        
    # Real Upload
    logger.info("🚀 Initiating YouTube upload...")
    upload_url = youtube_service.upload_video(
        str(video_path),
        title,
        description,
        tags,
        str(thumb_path) if thumb_path.exists() else None
    )
    
    if upload_url:
        logger.info(f"✅ YouTube Upload Success: {upload_url}")
        
        # Log to Database
        db_manager.log_episode(episode_id, podcast_name, original_title)
        short_id = db_manager.log_short(
            episode_id,
            start_time,
            end_time,
            title.replace(" #shorts", ""),
            viral_score=viral_score
        )
        db_manager.mark_short_uploaded(short_id, upload_url)
        logger.info("💾 Saved upload logs to SQLite Database.")
        
        # Send Notifications
        try:
            notification_service.broadcast(
                title=title.replace(" #shorts", ""),
                url=upload_url,
                thumbnail_path=str(thumb_path) if thumb_path.exists() else None
            )
            logger.info("🔔 Sent notifications to configured channels.")
        except Exception as e:
            logger.warning(f"Notification broadcast failed: {e}")
            
        # Clean up queue package directory
        try:
            shutil.rmtree(package_dir)
            logger.info(f"🧹 Cleaned up queue package directory: {package_dir}")
        except Exception as e:
            logger.warning(f"Failed to clean up package directory: {e}")
            
        return 0
    else:
        logger.error("❌ FAILED: YouTube upload failed. Keep package in queue for retry.")
        return 1

if __name__ == "__main__":
    import json
    from typing import Optional
    
    parser = argparse.ArgumentParser(description="Upload the next available short from the local queue to YouTube.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate upload without actual YouTube publication.")
    args = parser.parse_args()
    
    status = upload_next(dry_run=args.dry_run)
    sys.exit(status)
