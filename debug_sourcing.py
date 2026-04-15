import os
from src.podcast_automation.services.downloader import downloader
from src.podcast_automation.config import settings
from src.podcast_automation.models import Podcast
from loguru import logger

def debug_sourcing():
    # 1. Test Metadata Fetching
    test_podcasts = [
        Podcast(name="The Ranveer Show", url="https://www.youtube.com/@RanveerAllahbadia", channel_id="UCPxMZIFE856tbTfdkdjzTSQ"),
        Podcast(name="WTF is with Nikhil Kamath", url="https://www.youtube.com/@NikhilKamath", channel_id="UCRv4waLxgUN0Z-yb2I1Fq4A")
    ]
    
    for pod in test_podcasts:
        print(f"\n[DEBUG] Testing sourcing for: {pod.name}")
        episode = downloader.fetch_latest_episode(pod)
        if episode:
            print(f"SUCCESS: Found episode: {episode['title']} ({episode.get('duration', 'N/A')}s)")
            video_id = episode['id']
            
            # 2. Test Audio Download (Layer 1 or 2)
            print(f"\n[DEBUG] Testing Audio Download for: {video_id}")
            audio_path = downloader.download_audio(video_id)
            if audio_path and os.path.exists(audio_path):
                print(f"SUCCESS: Audio saved to {audio_path}")
                # os.remove(audio_path)
            else:
                print("FAILED: Audio download failed across all layers.")

            # 3. Test Segment Slicing (Layer 1 or 2)
            print(f"\n[DEBUG] Testing Video Segment Slicing (10s clip)")
            segment_path = downloader.download_video_segment(video_id, 60, 70)
            if segment_path and os.path.exists(segment_path):
                print(f"SUCCESS: Segment saved to {segment_path}")
                # os.remove(segment_path)
            else:
                print("FAILED: Segment download failed across all layers.")
        else:
            print(f"FAILED: Could not find any episodes for {pod.name}")

if __name__ == "__main__":
    debug_sourcing()
