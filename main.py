import os
import sys
import time
from database import init_db, log_episode, log_short, mark_short_uploaded
from source_podcast import get_random_podcast, fetch_latest_episode_audio, download_video_segment
from extract_highlights import transcribe_audio, find_best_highlight
from video_generator import create_video
from thumbnail_generator import create_thumbnail
from youtube_uploader import upload_video
import requests

def send_discord_webhook(title, url):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    data = {"content": f"🚀 **New Video Live!**\n*{title}*\nWatch here: {url}"}
    try:
        requests.post(webhook_url, json=data)
        print("Discord notification sent.")
    except Exception as e:
        print(f"Webhook failed: {e}")

def main():
    print("Starting Fully Automated Podcast Shorts Pipeline...")
    init_db()
    
    # 1. Source Podcast Audio
    podcast = get_random_podcast()
    print(f"Selected Podcast: {podcast['name']}")
    
    video_id, title, audio_file = fetch_latest_episode_audio(podcast['url'])
    if not video_id:
        print("No new episodes found. Exiting.")
        sys.exit(0)
    
    if not audio_file:
        print("Audio was not downloaded (maybe already processed). Exiting.")
        sys.exit(0)
        
    log_episode(video_id, podcast['name'], title)
    
    # 2. Extract Highlight
    print("Transcribing audio...")
    transcript = transcribe_audio(audio_file)
    
    highlight = find_best_highlight(transcript, target_duration=60)
    if not highlight:
        print("Could not find a valid highlight. Exiting.")
        sys.exit(1)
        
    start_time = highlight['start_time']
    end_time = highlight['end_time']
    short_title = highlight['title']
    reason = highlight.get('reason', '')
    hashtags = highlight.get('hashtags', ["podcast", "clips", "shorts"])
    b_roll_keyword = highlight.get('b_roll_keyword', None)
    
    print(f"Extraction Reason: {reason}")
    short_id = log_short(video_id, start_time, end_time, short_title)
    
    # 3. Download EXACT 60s Video Segment
    segment_file = f"temp_segment_{video_id}.mp4"
    if os.path.exists(segment_file):
        os.remove(segment_file)
        
    download_video_segment(video_id, start_time, end_time, segment_file)
    
    # 4. Process Video (Face Tracking + Crop + Kinetic Text)
    final_video_path = f"final_short_{video_id}.mp4"
    if os.path.exists(final_video_path):
        os.remove(final_video_path)
        
    create_video(segment_file, short_title, b_roll_keyword=b_roll_keyword, output_path=final_video_path)
    
    # 5. Create Thumbnail
    thumb_path = f"thumbnail_{video_id}.jpg"
    create_thumbnail(short_title, output_file=thumb_path)
    
    # 6. Upload to YouTube
    hashtag_str = " ".join([f"#{t.replace(' ', '').replace('#', '')}" for t in hashtags])
    description = f"🔥 {short_title}\n\nCredit: {podcast['name']} - {title}\n\nSubscribe to 60-Seconds Bytes for daily highlights!\n{hashtag_str}"
    
    tags = hashtags + [podcast['name']]
    
    upload_url = upload_video(final_video_path, short_title + " #shorts", description, tags, thumb_path)
    
    if upload_url:
        mark_short_uploaded(short_id, upload_url)
        print(f"✅ Pipeline Successfully Completed! Video live at: {upload_url}")
        send_discord_webhook(short_title, upload_url)
    else:
        print("❌ Upload failed, but video was generated.")
        
    # Cleanup
    for f in [audio_file, segment_file, final_video_path, thumb_path]:
        if f and os.path.exists(f):
            try:
                os.remove(f)
            except Exception as e:
                pass

if __name__ == "__main__":
    main()
