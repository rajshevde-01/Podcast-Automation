"""Test actual channel discovery methods to find what works."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Test 1: Check if RSS feed format changed
import requests
print("=" * 60)
print("TEST 1: Raw RSS Feed Check")
print("=" * 60)
# Use a known popular channel
test_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCPxMZIFE856tbTfdkdjzTSQ"
r = requests.get(test_url, timeout=10)
print(f"Status: {r.status_code}")
print(f"Content length: {len(r.text)}")
print(f"First 500 chars: {r.text[:500]}")
print()

# Test 2: Check if channel IDs in JSON are actual UC... format
print("=" * 60)
print("TEST 2: Channel ID Format Check")
print("=" * 60)
with open('podcasts_list.json', 'r') as f:
    data = json.load(f)
all_pods = data.get('india_top_10', []) + data.get('world_top_20', [])
for p in all_pods[:5]:
    cid = p.get('channel_id', '')
    name = p.get('name', '?')
    print(f"  {name}: channel_id='{cid}' (starts with UC: {cid.startswith('UC')})")
print()

# Test 3: yt-dlp channel discovery
print("=" * 60)
print("TEST 3: yt-dlp Channel Discovery (first 3 channels)")
print("=" * 60)
import yt_dlp
for p in all_pods[:3]:
    cid = p.get('channel_id', '')
    name = p.get('name', '?')
    url = f"https://www.youtube.com/channel/{cid}/videos"
    print(f"\n  Trying {name}: {url}")
    try:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlist_items': '1-3',
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            entries = list(info.get('entries', []))
            print(f"  ✅ Found {len(entries)} videos")
            for e in entries[:3]:
                vid_id = e.get('id', '?')
                title = e.get('title', '?')
                duration = e.get('duration', 0)
                print(f"     {vid_id} | {duration}s | {title[:60]}")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
