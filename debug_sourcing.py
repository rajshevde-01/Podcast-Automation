import os
from src.podcast_automation.services.downloader import downloader
from src.podcast_automation.services.youtube import youtube_service
from src.podcast_automation.config import settings
from src.podcast_automation.models import Podcast
from loguru import logger

def debug_sourcing():
    # 1. Test Official Metadata Discovery
    test_podcasts = [
        Podcast(name="The Ranveer Show", url="https://www.youtube.com/@RanveerAllahbadia", channel_id="UCPxMZIFE856tbTfdkdjzTSQ"),
        Podcast(name="WTF is with Nikhil Kamath", url="https://www.youtube.com/@NikhilKamath", channel_id="UCRv4waLxgUN0Z-yb2I1Fq4A")
    ]
    
    for pod in test_podcasts:
        print(f"\n[DEBUG] Testing Official Discovery for: {pod.name}")
        episode = downloader.fetch_latest_episode(pod)
        if episode:
            print(f"SUCCESS: Found episode: {episode['title']} ({episode.get('duration', 'N/A')}s)")
            video_id = episode['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # 2. Test Cobalt Download
            print(f"\n[DEBUG] Testing Cobalt Audio Download for: {video_id}")
            audio_path = str(settings.DATA_DIR / f"test_audio_{video_id}.m4a")
            # Using private method to specifically test Cobalt
            success = downloader._download_via_cobalt(video_url, audio_path, is_audio=True)
            if success and os.path.exists(audio_path):
                print(f"SUCCESS: Audio saved to {audio_path}")
                os.remove(audio_path)
            else:
                print("FAILED: Cobalt audio download failed.")

            # 3. Test Cobalt Slicing
            print(f"\n[DEBUG] Testing Cobalt Video Segment Slicing (10s clip)")
            segment_path = str(settings.DATA_DIR / f"test_segment_{video_id}.mp4")
            success = downloader._download_via_cobalt(video_url, segment_path, is_audio=False, start_time=60, end_time=70)
            if success and os.path.exists(segment_path):
                print(f"SUCCESS: Segment saved to {segment_path}")
                os.remove(segment_path)
            else:
                print("FAILED: Cobalt segment slicing failed.")
        else:
            print(f"FAILED: Could not find any long-form episodes for {pod.name} via Official API.")

if __name__ == "__main__":
    debug_sourcing()
