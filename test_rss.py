"""Test RSS feeds for all channels to find which work."""
import requests, re, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('podcasts_list.json', 'r') as f:
    data = json.load(f)

all_pods = data.get('india_top_10', []) + data.get('world_top_20', [])

working = 0
broken = 0

for p in all_pods:
    cid = p.get('channel_id', '')
    name = p.get('name', '?')
    if not cid:
        print(f"  SKIP {name} (no channel_id)")
        continue

    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    try:
        r = requests.get(url, timeout=10)
        ids = re.findall(r'<yt:videoId>(.*?)</yt:videoId>', r.text)
        if ids:
            print(f"  ✅ {name:40s} | {len(ids):2d} videos | {ids[0]}")
            working += 1
        else:
            print(f"  ❌ {name:40s} | 0 videos (RSS empty)")
            broken += 1
    except Exception as e:
        print(f"  ❌ {name:40s} | ERROR: {e}")
        broken += 1

print(f"\nSummary: {working} working, {broken} broken out of {len(all_pods)} channels")
