import os
import cv2
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import urllib.request
import random
from typing import List, Dict, Optional
from loguru import logger
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, ImageClip, ColorClip, VideoClip
from ..config import settings

class VideoService:
    def __init__(self, width: int = settings.VIDEO_WIDTH, height: int = settings.VIDEO_HEIGHT):
        self.width = width
        self.height = height
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    def _get_face_center_x(self, frame) -> Optional[int]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) == 0:
            return None
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = largest_face
        return x + w // 2

    def create_video(self, video_path: str, title: str, words: List[Dict], b_roll_keyword: Optional[str] = None) -> Optional[str]:
        logger.info(f"Processing Video: {video_path}")
        clip = VideoFileClip(video_path)
        w_in, h_in = clip.size
        duration = clip.duration
        
        target_aspect = self.width / self.height
        crop_w = int(h_in * target_aspect)
        
        smoothed_x = w_in // 2
        
        def auto_crop_frame(get_frame, t):
            nonlocal smoothed_x
            frame = get_frame(t)
            if int(t * 10) % 2 == 0:
                face_x = self._get_face_center_x(frame)
                if face_x is not None:
                    smoothed_x = int(0.2 * face_x + 0.8 * smoothed_x)
            
            x1 = max(0, min(w_in - crop_w, smoothed_x - crop_w // 2))
            x2 = x1 + crop_w
            cropped = frame[:, x1:x2]
            return cv2.resize(cropped, (self.width, self.height))

        # 1. Base Clip (Auto-Crop)
        base_clip = clip.fl(auto_crop_frame)
        clips = [base_clip]
        
        # 2. B-Roll Flash
        if b_roll_keyword:
            broll_path = str(settings.DATA_DIR / f"broll_{b_roll_keyword}.jpg")
            try:
                url = f"https://loremflickr.com/{self.width}/{self.height//2}/{b_roll_keyword}"
                urllib.request.urlretrieve(url, broll_path)
                broll_clip = ImageClip(broll_path).resize((self.width, self.height//2))
                broll_clip = broll_clip.set_position(('center', 'top')).set_start(0).set_duration(2.5).crossfadeout(0.5)
                clips.append(broll_clip)
            except Exception as e:
                logger.warning(f"Failed to fetch B-Roll: {e}")

        # 3. Branding/Title at Top
        title_clip = TextClip(
            title, fontsize=65, color='white', font='Arial-Bold',
            stroke_color='black', stroke_width=4, method='caption', size=(self.width - 120, None)
        ).set_position(('center', 150)).set_duration(duration)
        clips.append(title_clip)
        
        # 4. Kinetic Subtitles
        logger.info("Generating kinetic subtitles...")
        chunks = []
        current_chunk = []
        chunk_start = 0.0
        for i, w in enumerate(words):
            if not current_chunk:
                chunk_start = w['start']
            current_chunk.append(w)
            if len(current_chunk) >= 4 or w['text'].endswith(('.', '!', '?')) or (i < len(words)-1 and words[i+1]['start'] - w['end'] > 0.5):
                end_t = w['end']
                if i < len(words)-1: end_t = words[i+1]['start']
                chunks.append((chunk_start, end_t, " ".join([word['text'] for word in current_chunk])))
                current_chunk = []

        for start_t, end_t, chunk_text in chunks:
            color = 'white'
            if any(kw in chunk_text.upper() for kw in ["INSANE", "MONEY", "CRAZY", "TRUTH"]):
                color = '#FFD700'
            
            txt_clip = TextClip(
                chunk_text, fontsize=95, color=color, font='Arial-Bold',
                stroke_color='black', stroke_width=6, method='caption', align='center', size=(self.width - 140, None)
            ).set_position(('center', self.height // 2 + 100)).set_start(start_t).set_duration(end_t - start_t)
            
            # Simple Pop animation
            # txt_clip = txt_clip.resize(lambda t: 1.0 + 0.05 * math.sin(t * math.pi / max(0.1, end_t-start_t)))
            clips.append(txt_clip)

        # 5. Progress Bar
        bar_h = 10
        def make_progress(t):
            prog = t / max(duration, 0.1)
            f = np.zeros((bar_h, self.width, 3), dtype=np.uint8)
            f[:, :int(self.width * prog)] = [0, 255, 136]
            return f
            
        progress_clip = VideoClip(make_progress, duration=duration).set_position(('center', self.height - bar_h - 10))
        clips.append(progress_clip)

        # Composite & Render
        output_path = str(settings.OUTPUT_DIR / f"final_short_{os.path.basename(video_path)}")
        logger.info(f"Rendering: {output_path}")
        
        final_video = CompositeVideoClip(clips, size=(self.width, self.height))
        final_video.write_videofile(output_path, fps=settings.FPS, codec='libx264', audio_codec='aac', preset='fast', threads=4)
        
        logger.info("✅ Rendering Complete.")
        return output_path

video_service = VideoService()
