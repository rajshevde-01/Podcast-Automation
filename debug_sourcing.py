import yt_dlp
import os
from src.podcast_automation.services.downloader import downloader
from src.podcast_automation.config import settings

def debug_sourcing():
    channel_url = "https://www.youtube.com/@NikhilKamath"
    print(f"DEBUG: Testing sourcing for {channel_url}")
    
    profiles = [
        {"name": "iOS App", "args": "youtube:player-client=ios"},
        {"name": "Android App", "args": "youtube:player-client=android"},
        {"name": "Web/MWeb", "args": "youtube:player-client=web,mweb"},
        {"name": "TV/Embedded", "args": "youtube:player-client=tv,web_embedded"},
    ]
    
    for profile in profiles:
        print(f"\n--- Testing Profile: {profile['name']} ---")
        opts = downloader.base_opts.copy()
        opts.update({
            'extractor_args': profile['args'],
            'quiet': False, # Show full output
            'no_warnings': False,
        })
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if 'entries' in info:
                    print(f"SUCCESS: Found {len(info['entries'])} entries.")
                    for i, entry in enumerate(info['entries'][:3]):
                        print(f"  [{i}] {entry.get('title')} ({entry.get('duration')}s)")
                else:
                    print("ERROR: No entries found in info.")
        except Exception as e:
            print(f"FAILED: {str(e)}")

if __name__ == "__main__":
    debug_sourcing()
