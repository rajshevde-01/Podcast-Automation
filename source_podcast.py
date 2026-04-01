import json
import random
import subprocess
import os
from database import is_episode_processed, log_episode

PODCASTS_FILE = "podcasts_list.json"

def get_random_podcast():
    with open(PODCASTS_FILE, 'r') as f:
        data = json.load(f)
    
    india_pods = data.get("india_top_10", [])
    world_pods = data.get("world_top_20", [])
    
    # 75% chance to pick from Indian YouTubers as requested
    if india_pods and (not world_pods or random.random() < 0.75):
        return random.choice(india_pods)
    elif world_pods:
        return random.choice(world_pods)
    return None

def fetch_latest_episode_audio(channel_url: str):
    """
    Uses yt-dlp to get the latest video from the channel.
    Downloads ONLY the audio format (m4a/webm) to save huge amounts of time/bandwidth.
    Returns: (video_id, title, audio_file_path)
    """
    print(f"Fetching latest episode from {channel_url}...")
    
    # Bypass flags for GitHub Actions
    # We use a mix of clients: TV and Web_Embedded are often more stable for downloads
    # while standard 'web' and 'mweb' work well with cookies.
    # Note: 'ios' and 'android' clients do NOT support cookies and are skipped by yt-dlp if --cookies is present.
    bypass_flags = [
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--extractor-args", "youtube:player-client=tv,web_embedded",
        "--add-header", "Accept-Language:en-US,en;q=0.9",
        "--add-header", "Origin:https://www.youtube.com",
        "--add-header", "Referer:https://www.youtube.com/",
        "--no-check-certificates",
        "--prefer-free-formats",
        "--youtube-skip-dash-manifest"
    ]
    
    if os.path.exists("cookies.txt"):
        print("Cookies file found. Using authenticated session for bypass...")
        bypass_flags.extend(["--cookies", "cookies.txt"])
    
    # Get metadata of the latest video in the channel
    cmd_meta = [
        "yt-dlp", channel_url,
        "--playlist-items", "1",
        "--dump-json",
        "--skip-download",
        "--match-filter", "duration > 600" # Only videos longer than 10 mins
    ] + bypass_flags
    
    try:
        result = subprocess.run(cmd_meta, capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            print("No suitable long-form video found.")
            return None, None, None
            
        video_info = json.loads(result.stdout.strip().split('\n')[0])
        video_id = video_info.get('id')
        title = video_info.get('title')
        
        print(f"Found latest episode: {title} ({video_id})")
        
        if is_episode_processed(video_id):
            print("This episode has already been processed.")
            return video_id, title, None
            
        # Download audio
        audio_filename = f"temp_audio_{video_id}.m4a"
        if os.path.exists(audio_filename):
            os.remove(audio_filename)
            
        cmd_download = [
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio",
            "-o", audio_filename,
            f"https://www.youtube.com/watch?v={video_id}"
        ] + bypass_flags
        
        print("Downloading audio track...")
        subprocess.run(cmd_download, check=True)
        
        return video_id, title, audio_filename

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        stdout = e.stdout or ""
        print(f"yt-dlp command failed with exit code {e.returncode}")
        print(f"STDERR: {stderr[:2000]}")
        print(f"STDOUT: {stdout[:500]}")
        
        bot_keywords = ["confirm you're not a bot", "Sign in to confirm", "bot", "captcha"]
        if any(kw.lower() in stderr.lower() for kw in bot_keywords):
            print("🛑 CRITICAL: YouTube detected this runner as a bot.")
            if os.path.exists("cookies.txt"):
                print("cookies.txt EXISTS but may be expired/invalid. Re-export from browser.")
            else:
                print("ACTION REQUIRED: Please upload a valid cookies.txt file.")
            raise Exception("YouTube Bot Detection Block. Cookies may be expired.")
            
        raise Exception(f"yt-dlp failed: {stderr[:500]}")

def download_video_segment(video_id: str, start_time: float, end_time: float, output_filename: str):
    """
    This is extremely efficient: it downloads ONLY the Specific 60s video chunk
    from YouTube without downloading the whole 2-hour video.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Downloading video segment {start_time} - {end_time}...")
    
    # Bypass flags (Synchronized with fetch_latest_episode_audio)
    bypass_flags = [
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--extractor-args", "youtube:player-client=tv,web_embedded",
        "--add-header", "Accept-Language:en-US,en;q=0.9",
        "--add-header", "Origin:https://www.youtube.com",
        "--add-header", "Referer:https://www.youtube.com/",
        "--no-check-certificates",
        "--prefer-free-formats",
        "--youtube-skip-dash-manifest"
    ]
    
    if os.path.exists("cookies.txt"):
        bypass_flags.extend(["--cookies", "cookies.txt"])
    
    # We download 1080p or 720p mp4 video
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best",
        "--download-sections", f"*{start_time}-{end_time}",
        "--force-keyframes-at-cuts",
        "-o", output_filename,
        url
    ] + bypass_flags
    
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return output_filename

if __name__ == "__main__":
    podcast = get_random_podcast()
    if podcast:
        print(f"Selected Podcast: {podcast['name']}")
        vid, title, audio_file = fetch_latest_episode_audio(podcast['url'])
        if audio_file:
            print(f"Success! Audio saved to {audio_file}")
    else:
        print("No podcasts defined in list.")
        # Next step would be transcribing and finding highlights, which will be in extract_highlights.py
