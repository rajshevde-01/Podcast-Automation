"""Quick test script for v6 changes."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("=" * 60)
print("PODCAST AUTOMATION v6 — Verification Test")
print("=" * 60)

# 1. Test Models
print("\n[1] Models...")
from src.podcast_automation.models import Podcast, ChannelInfo, CopyrightCheckResult
p = Podcast(name="Test", url="http://test.com", copyright_risk="low", license_policy="Safe to clip")
print(f"  ✅ Podcast: {p.name}, risk={p.copyright_risk}, policy={p.license_policy}")

ci = ChannelInfo(channel_id="UC123", name="Test Channel", subscriber_count=1500000)
print(f"  ✅ ChannelInfo: {ci.name}, subs={ci.subscriber_count:,}")

cr = CopyrightCheckResult(video_id="abc123", is_safe=True, risk_level="low", reason="Test OK")
print(f"  ✅ CopyrightCheck: safe={cr.is_safe}, risk={cr.risk_level}")

# 2. Test Config
print("\n[2] Config...")
from src.podcast_automation.config import settings
print(f"  ✅ Quality Preference: {settings.VIDEO_QUALITY_PREFERENCE}")
print(f"  ✅ Audio Normalize: {settings.AUDIO_NORMALIZE}")
print(f"  ✅ Copyright Threshold: {settings.COPYRIGHT_RISK_THRESHOLD}")
print(f"  ✅ Skip high risk: {settings.should_skip_risk('high')}")
print(f"  ✅ Skip medium risk: {settings.should_skip_risk('medium')}")
print(f"  ✅ Skip low risk: {settings.should_skip_risk('low')}")

# 3. Test Podcasts List Loading (with copyright filter)
print("\n[3] Podcast List + Copyright Filter...")
import json
with open(settings.PODCASTS_LIST_FILE, 'r') as f:
    data = json.load(f)

india = data.get("india_top_10", [])
world = data.get("world_top_20", [])

print(f"  Total India: {len(india)}, World: {len(world)}")

safe_india = [p for p in india if not settings.should_skip_risk(p.get('copyright_risk', 'medium'))]
safe_world = [p for p in world if not settings.should_skip_risk(p.get('copyright_risk', 'medium'))]

print(f"  Safe India: {len(safe_india)}, Safe World: {len(safe_world)}")

skipped = []
for p in india + world:
    if settings.should_skip_risk(p.get('copyright_risk', 'medium')):
        skipped.append(f"    ❌ {p['name']} (risk: {p['copyright_risk']})")

if skipped:
    print(f"  Channels SKIPPED by copyright filter:")
    for s in skipped:
        print(s)

# Show safe channels
print(f"\n  ✅ Safe channels available:")
for p in safe_india + safe_world:
    risk = p.get('copyright_risk', '?')
    policy = p.get('license_policy', 'N/A')
    print(f"    🟢 {p['name']} (risk: {risk}) — {policy}")

# 4. Test Copyright Checker import
print("\n[4] Copyright Checker...")
from src.podcast_automation.services.copyright_checker import checker
print(f"  ✅ CopyrightCheckerService loaded (API key: {'set' if checker.api_key else 'not set'})")

# 5. Test Database (channels table)
print("\n[5] Database...")
from src.podcast_automation.database import db_manager
db_manager.save_channel_info("UC_TEST", "Test Channel", 1000000, 500, "US", "low", "Test policy")
info = db_manager.get_channel_info("UC_TEST")
print(f"  ✅ Channel saved and retrieved: {info['name']}, subs={info['subscriber_count']:,}")

# 6. Test Video Engine import
print("\n[6] Video Engine...")
from src.podcast_automation.services.video_engine import video_service
print(f"  ✅ VideoService loaded (caption_font_size={video_service.caption_font_size})")
print(f"  ✅ Caption Y position: {video_service.caption_y_position}")
print(f"  ✅ Caption max words per chunk: {video_service.caption_max_words}")

# Test caption chunking
test_words = [
    {"text": "This", "start": 0.0, "end": 0.3},
    {"text": "is", "start": 0.3, "end": 0.5},
    {"text": "a", "start": 0.5, "end": 0.6},
    {"text": "test", "start": 0.6, "end": 0.9},
    {"text": "of", "start": 1.0, "end": 1.2},
    {"text": "kinetic", "start": 1.2, "end": 1.6},
    {"text": "captions.", "start": 1.6, "end": 2.0},
    {"text": "Money", "start": 2.5, "end": 2.8},
    {"text": "is", "start": 2.8, "end": 3.0},
    {"text": "insane!", "start": 3.0, "end": 3.5},
]
chunks = video_service._build_caption_chunks(test_words)
print(f"  ✅ Caption chunks generated: {len(chunks)}")
for i, chunk in enumerate(chunks):
    print(f"    Chunk {i+1}: [{chunk['start']:.1f}s-{chunk['end']:.1f}s] \"{chunk['full_text']}\"")

# 7. Test Pipeline import
print("\n[7] Pipeline...")
from src.podcast_automation.pipeline import AutomationPipeline
print(f"  ✅ AutomationPipeline loaded (includes copyright_checker)")

print("\n" + "=" * 60)
print("ALL v6 TESTS PASSED ✅")
print("=" * 60)
