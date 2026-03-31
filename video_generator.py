import os
import cv2
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import urllib.request
import random

# Handle Pillow compatibility
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, ImageClip, ColorClip, VideoClip
from faster_whisper import WhisperModel

W_OUT, H_OUT = 1080, 1920

def transcribe_words(video_path):
    print(f"Transcribing {video_path} for word-level timestamps...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, info = model.transcribe(video_path, word_timestamps=True)
    
    words = []
    for segment in segments:
        for word in segment.words:
            words.append({
                "start": word.start,
                "end": word.end,
                "text": word.word.strip()
            })
    return words

def get_face_center_x(frame, face_cascade):
    """Detects the largest face in the frame and returns its X center."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    if len(faces) == 0:
        return None
        
    # Find largest face
    largest_face = max(faces, key=lambda f: f[2] * f[3])
    x, y, w, h = largest_face
    return x + w // 2

def get_broll_image(keyword, output_path="temp_broll.jpg"):
    if not keyword or keyword.strip() == "":
        return None
    try:
        print(f"Fetching B-Roll image for keyword: {keyword}...")
        url = f"https://loremflickr.com/1080/960/{keyword}"
        urllib.request.urlretrieve(url, output_path)
        return output_path
    except Exception as e:
        print(f"Failed to fetch B-Roll: {e}")
        return None

def create_video(video_path, title, b_roll_keyword=None, output_path="output_short.mp4"):
    print(f"Processing video: {video_path}")
    
    clip = VideoFileClip(video_path)
    if clip.rotation in (90, 270):
        clip = clip.resize(clip.size[::-1])
        clip.rotation = 0
        
    w_in, h_in = clip.size
    duration = clip.duration
    
    # 1. Face Tracking & Auto-Cropping
    print("Running face tracking pass...")
    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(cascade_path)
    
    target_aspect = 9 / 16
    crop_w = int(h_in * target_aspect)
    crop_h = h_in
    
    # Track smoothed X position across frames
    smoothed_x = w_in // 2
    
    def auto_crop_frame(get_frame, t):
        nonlocal smoothed_x
        frame = get_frame(t)
        
        # Only detect face every 0.2s to save massive generic processing
        # and rely on smoothed value
        if int(t * 10) % 2 == 0:
            face_x = get_face_center_x(frame, face_cascade)
            if face_x is not None:
                # Smooth movement (exponential moving average)
                smoothed_x = int(0.2 * face_x + 0.8 * smoothed_x)
        
        # Bound the crop window
        x1 = max(0, smoothed_x - crop_w // 2)
        x2 = x1 + crop_w
        if x2 > w_in:
            x2 = w_in
            x1 = w_in - crop_w
            
        cropped = frame[:, x1:x2]
        # Resize to vertical bounds. If split screen, we only need top half.
        return cv2.resize(cropped, (W_OUT, H_OUT), interpolation=cv2.INTER_LANCZOS4)

    # 1.5 Split-Screen Logic (Triggered Once a Week)
    from datetime import datetime
    satisfying_path = "assets/satisfying.mp4"
    if os.path.exists(satisfying_path) and datetime.today().weekday() == 6:  # 6 is Sunday
        print("Satisfying video found and it's Sunday! Generating weekly split-screen...")
        # Crop podcast to top half
        top_clip = clip.fl(auto_crop_frame).crop(y1=0, y2=H_OUT//2)
        top_clip = top_clip.set_position(('center', 'top'))
        
        # Load satisfying video for bottom half
        bot_clip = VideoFileClip(satisfying_path)
        # Random start time for variety
        if bot_clip.duration > duration:
            start_t = random.uniform(0, bot_clip.duration - duration)
            bot_clip = bot_clip.subclip(start_t, start_t + duration)
        else:
            bot_clip = bot_clip.set_duration(duration).loop()
            
        # Crop/Resize satisfying video to fit bottom half (1080x960)
        bot_w, bot_h = bot_clip.size
        target_bot_aspect = W_OUT / (H_OUT // 2)
        current_bot_aspect = bot_w / bot_h
        
        if current_bot_aspect > target_bot_aspect:
            # Video is wider
            new_w = int(bot_h * target_bot_aspect)
            x1 = (bot_w - new_w) // 2
            bot_clip = bot_clip.crop(x1=x1, width=new_w).resize((W_OUT, H_OUT//2))
        else:
            # Video is taller
            new_h = int(bot_w / target_bot_aspect)
            y1 = (bot_h - new_h) // 2
            bot_clip = bot_clip.crop(y1=y1, height=new_h).resize((W_OUT, H_OUT//2))
            
        bot_clip = bot_clip.set_position(('center', 'bottom'))
        base_clip = CompositeVideoClip([top_clip, bot_clip], size=(W_OUT, H_OUT))
    else:
        print("No satisfying video found. Using full-screen crop.")
        base_clip = clip.fl(auto_crop_frame)
    
    # 2. Add B-Roll Flash if keyword provided
    clips = [base_clip]
    
    if b_roll_keyword:
        broll_path = get_broll_image(b_roll_keyword)
        if broll_path:
            # Flash for the first 2.5 seconds over the top half
            broll_clip = ImageClip(broll_path).resize((W_OUT, H_OUT//2))
            broll_clip = broll_clip.set_position(('center', 'top')).set_start(0).set_duration(2.5)
            broll_clip = broll_clip.crossfadeout(0.3)
            clips.append(broll_clip)

    # 3. Get Word-level Timestamps
    words = transcribe_words(video_path)
    
    # 3. Add Podcast Branding / Title at the Top
    title_clip = TextClip(
        title, fontsize=65, color='white',
        font='Arial-Bold', stroke_color='black', stroke_width=4,
        method='caption', size=(W_OUT - 120, None)
    ).set_position(('center', 150)).set_duration(duration)
    clips.append(title_clip)
    
    # 4. Kinetic Subtitles Generation
    print("Generating kinetic subtitles...")
    
    # Group words into chunks of 3-4 so they appear at once and stay
    chunks = []
    current_chunk = []
    chunk_start = 0.0
    for i, w in enumerate(words):
        if not current_chunk:
            chunk_start = w['start']
        current_chunk.append(w)
        
        # End chunk if 4 words or sentence boundary
        if len(current_chunk) >= 4 or w['text'].endswith(('.', '!', '?')) or (i < len(words)-1 and words[i+1]['start'] - w['end'] > 0.5):
            end_time = w['end']
            if i < len(words)-1:
                end_time = words[i+1]['start'] # extend to next word
            chunks.append((chunk_start, end_time, current_chunk))
            current_chunk = []

    for start_t, end_t, word_list in chunks:
        chunk_text = " ".join([w['text'] for w in word_list])
        
        # Determine color for highlights
        color = 'white'
        if any(keyword in chunk_text.upper() for keyword in ["INSANE", "MONEY", "CRAZY", "HACK", "TRUTH"]):
            color = '#FFD700' # Gold
        
        txt_clip = TextClip(
            chunk_text, fontsize=95, color=color,
            font='Arial-Bold', stroke_color='black', stroke_width=6,
            method='caption', align='center', size=(W_OUT - 140, None)
        )
        
        # Bouncing pop effect
        dur = end_t - start_t
        txt_clip = txt_clip.resize(lambda t: 1.0 + 0.1 * math.sin(t * math.pi / max(dur, 0.1)))
        
        txt_clip = txt_clip.set_position(('center', H_OUT // 2 + 100))
        txt_clip = txt_clip.set_start(start_t).set_duration(end_t - start_t)
        clips.append(txt_clip)

    # 5. Bottom Progress Bar
    bar_h = 10
    def make_progress(t):
        progress = t / max(duration, 0.1)
        bar_w = int(W_OUT * progress)
        frame = np.zeros((bar_h, W_OUT, 3), dtype=np.uint8)
        if bar_w > 0:
            frame[:, :bar_w] = [0, 255, 136] # Green progress
        return frame
    progress_clip = VideoClip(make_progress, duration=duration).set_position(('center', H_OUT - bar_h - 10))
    clips.append(progress_clip)

    print("Compositing and rendering final short...")
    final = CompositeVideoClip(clips)
    
    # Use GPU hardware decoding if available, otherwise fast CPU threads
    final.write_videofile(
        output_path,
        fps=30,
        codec='libx264',
        audio_codec='aac',
        preset='fast',
        threads=4
    )
    print("Done rendering video!")
    return output_path

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        create_video(sys.argv[1], "Viral Podcast Moment", b_roll_keyword="money")
    else:
        print("Usage: python video_generator.py <input.mp4>")
