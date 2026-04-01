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
    
    # Client profiles to rotate through
    profiles = [
        {"name": "Authenticated Web/MWeb", "args": "youtube:player-client=web,mweb", "use_cookies": True},
        {"name": "Authenticated TV/Embedded", "args": "youtube:player-client=tv,web_embedded", "use_cookies": True},
        {"name": "Anonymous Android", "args": "youtube:player-client=android", "use_cookies": False},
        {"name": "Anonymous iOS", "args": "youtube:player-client=ios", "use_cookies": False},
    ]
    
    last_error = ""
    for profile in profiles:
        print(f"Trying bypass profile: {profile['name']}...")
        
        current_flags = [
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--extractor-args", str(profile["args"]),
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--add-header", "Origin:https://www.youtube.com",
            "--add-header", "Referer:https://www.youtube.com/",
            "--no-check-certificates",
            "--prefer-free-formats",
            "--youtube-skip-dash-manifest"
        ]
        
        if profile["use_cookies"] and os.path.exists("cookies.txt"):
            current_flags.extend(["--cookies", "cookies.txt"])
            
        cmd_meta = [
            "yt-dlp", channel_url,
            "--playlist-items", "1",
            "--dump-json",
            "--skip-download",
            "--match-filter", "duration > 600"
        ] + current_flags
        
        try:
            result = subprocess.run(cmd_meta, capture_output=True, text=True, check=True)
            if not result.stdout.strip():
                continue # Try next profile
                
            video_info = json.loads(result.stdout.strip().split('\n')[0])
            video_id = video_info.get('id')
            title = video_info.get('title')
            
            print(f"✅ Success with profile {profile['name']}! Found: {title} ({video_id})")
            
            if is_episode_processed(video_id):
                print("This episode has already been processed.")
                return video_id, title, None
                
            # Download audio with WORKING current_flags
            audio_filename = f"temp_audio_{video_id}.m4a"
            if os.path.exists(audio_filename):
                os.remove(audio_filename)
                
            cmd_download = [
                "yt-dlp",
                "-f", "bestaudio[ext=m4a]/bestaudio",
                "-o", audio_filename,
                f"https://www.youtube.com/watch?v={video_id}"
            ] + current_flags
            
            print("Downloading audio track...")
            subprocess.run(cmd_download, check=True)
            
            return video_id, title, audio_filename

        except subprocess.CalledProcessError as e:
            last_error = e.stderr or ""
            print(f"Profile {profile['name']} failed.")
            continue
            
    print(f"🛑 ALL BYPASS PROFILES FAILED.")
    print(f"Last Error Sample: {last_error[:500]}")
    
    if any(kw.lower() in last_error.lower() for kw in ["bot", "captcha", "confirm you're not a bot", "Sign in to confirm"]):
        print("ACTION REQUIRED: YouTube is aggressively blocking this runner. Update cookies.txt or provide a PO Token.")
        raise Exception("YouTube Bot Detection Block. ALL profiles failed.")
        
    raise Exception(f"yt-dlp failed after trying all profiles: {last_error[:200]}")

def download_video_segment(video_id: str, start_time: float, end_time: float, output_filename: str):
    """
    This is extremely efficient: it downloads ONLY the Specific 60s video chunk
    from YouTube without downloading the whole 2-hour video.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Downloading video segment {start_time} - {end_time}...")
    
    # Use Anonymous iOS for segments as it is currently the most robust for large downloads
    bypass_flags = [
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--extractor-args", "youtube:player-client=ios",
        "--add-header", "Accept-Language:en-US,en;q=0.9",
        "--add-header", "Origin:https://www.youtube.com",
        "--add-header", "Referer:https://www.youtube.com/",
        "--no-check-certificates",
        "--prefer-free-formats",
        "--youtube-skip-dash-manifest"
    ]
    
    # Only add cookies if not using iOS/Android as it confuses yt-dlp
    # if os.path.exists("cookies.txt"):
    #     bypass_flags.extend(["--cookies", "cookies.txt"])
    
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
