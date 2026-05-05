"""
Video Engine v6 — Premium Kinetic Live Captions

Features:
  - Word-by-word pop-in animation with scale bounce
  - Active word highlighting (gold for current, white for previous)
  - Semi-transparent background pill behind caption groups
  - Emoji keyword insertion for viral keywords
  - Smooth face-tracking auto-crop for 9:16
  - Attribution credit bar at bottom
  - Progress bar with gradient
"""

import os
import cv2
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import urllib.request
import random
from typing import List, Dict, Optional, Tuple
from loguru import logger
from moviepy.editor import (
    VideoFileClip, TextClip, CompositeVideoClip,
    ImageClip, ColorClip, VideoClip, AudioFileClip
)
import moviepy.video.fx.all as vfx
from ..config import settings

# Emoji mapping for viral keyword highlighting
EMOJI_KEYWORDS = {
    "money": "💰", "rich": "💰", "million": "💰", "billion": "💰", "dollar": "💰",
    "insane": "🤯", "crazy": "🤯", "wild": "🤯", "unbelievable": "🤯",
    "truth": "💡", "secret": "🤫", "hack": "⚡", "tip": "💡",
    "love": "❤️", "hate": "😤", "angry": "😤", "fire": "🔥",
    "brain": "🧠", "mind": "🧠", "think": "🧠", "smart": "🧠",
    "dead": "💀", "kill": "💀", "die": "💀",
    "god": "🙏", "pray": "🙏", "faith": "🙏",
    "win": "🏆", "success": "🏆", "champion": "🏆",
    "fail": "❌", "lose": "❌", "wrong": "❌",
    "wow": "😱", "amazing": "😱", "incredible": "😱",
}

# High-impact words that get gold highlighting
HIGHLIGHT_WORDS = {
    "insane", "money", "crazy", "truth", "secret", "million", "billion",
    "rich", "powerful", "dangerous", "shocking", "breaking", "exposed",
    "hack", "free", "impossible", "never", "always", "biggest", "worst",
    "best", "first", "last", "only", "dead", "kill", "fire", "god",
    "amazing", "incredible", "unbelievable", "legendary", "epic",
}


class VideoService:
    def __init__(self, width: int = settings.VIDEO_WIDTH, height: int = settings.VIDEO_HEIGHT):
        self.width = width
        self.height = height
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # Caption styling constants
        self.caption_font_size = 90
        self.caption_y_position = int(self.height * 0.62)  # Lower third area
        self.caption_max_words = 4  # Words per caption group
        self.pill_padding_x = 40
        self.pill_padding_y = 20
        self.pill_corner_radius = 25
        self.pill_bg_color = (0, 0, 0, 160)  # Semi-transparent black

    def _get_face_center_x(self, frame) -> Optional[int]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) == 0:
            return None
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = largest_face
        return x + w // 2

    def _get_font(self, size: int) -> ImageFont:
        """Try to load a bold font, fallback to default."""
        font_candidates = ["arialbd.ttf", "Arial-Bold", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
        for font_name in font_candidates:
            try:
                return ImageFont.truetype(font_name, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()

    def _create_pil_text_clip(self, text: str, fontsize: int = 40, 
                               color: Tuple[int, ...] = (255, 255, 255),
                               stroke_color: Tuple[int, ...] = (0, 0, 0),
                               stroke_width: int = 2,
                               max_width: int = None, y_position: int = 0) -> Optional[ImageClip]:
        """
        Creates a static text overlay using PIL (no ImageMagick needed).
        Returns a moviepy ImageClip positioned on the frame.
        """
        if max_width is None:
            max_width = self.width - 100
        
        try:
            font = self._get_font(fontsize)
            
            # Word wrap
            draw_tmp = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
            words_list = text.split()
            lines = []
            current_line = []
            for word in words_list:
                current_line.append(word)
                test_text = " ".join(current_line)
                bbox = draw_tmp.textbbox((0, 0), test_text, font=font)
                if bbox[2] - bbox[0] > max_width:
                    current_line.pop()
                    if current_line:
                        lines.append(" ".join(current_line))
                    current_line = [word]
            if current_line:
                lines.append(" ".join(current_line))
            
            # Measure total height
            line_height = font.getbbox("Ay")[3] - font.getbbox("Ay")[1] + 10
            total_height = line_height * len(lines)
            
            # Create image
            img = Image.new('RGBA', (self.width, total_height + 20), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            y = 5
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                text_w = bbox[2] - bbox[0]
                x = (self.width - text_w) // 2
                
                # Draw stroke
                for dx in range(-stroke_width, stroke_width + 1):
                    for dy in range(-stroke_width, stroke_width + 1):
                        if dx * dx + dy * dy <= stroke_width * stroke_width:
                            draw.text((x + dx, y + dy), line, fill=stroke_color + (255,), font=font)
                # Draw main text
                draw.text((x, y), line, fill=color + (255,), font=font)
                y += line_height
            
            clip = ImageClip(np.array(img))
            clip = clip.set_position(('center', y_position))
            return clip
        except Exception as e:
            logger.warning(f"PIL text clip creation failed: {e}")
            return None

    def _build_caption_chunks(self, words: List[Dict]) -> List[Dict]:
        """
        Groups words into caption chunks of 3-4 words each.
        Returns list of: { "start", "end", "words": [{"text", "start", "end"}], "full_text" }
        """
        chunks = []
        current_chunk_words = []
        chunk_start = 0.0

        for i, w in enumerate(words):
            if not current_chunk_words:
                chunk_start = w['start']
            current_chunk_words.append(w)

            # Chunk break conditions
            is_punctuation_end = w['text'].rstrip().endswith(('.', '!', '?', ','))
            is_chunk_full = len(current_chunk_words) >= self.caption_max_words
            has_long_pause = (i < len(words) - 1 and words[i + 1]['start'] - w['end'] > 0.5)
            is_last_word = (i == len(words) - 1)

            if is_chunk_full or is_punctuation_end or has_long_pause or is_last_word:
                chunk_end = w['end']
                # Extend end time to next word start if not last
                if i < len(words) - 1:
                    chunk_end = words[i + 1]['start']

                full_text = " ".join([word['text'] for word in current_chunk_words])

                chunks.append({
                    "start": chunk_start,
                    "end": chunk_end,
                    "words": list(current_chunk_words),
                    "full_text": full_text,
                })
                current_chunk_words = []

        return chunks

    def _get_emoji_for_word(self, word: str) -> str:
        """Returns an emoji prefix if the word matches a keyword."""
        clean = word.lower().strip(".,!?\"'()[]{}:;")
        return EMOJI_KEYWORDS.get(clean, "")

    def _is_highlight_word(self, word: str) -> bool:
        """Returns True if this word should be highlighted in gold."""
        clean = word.lower().strip(".,!?\"'()[]{}:;")
        return clean in HIGHLIGHT_WORDS

    def _render_caption_frame(self, chunk: Dict, t: float, frame_w: int, frame_h: int) -> np.ndarray:
        """
        Renders a single caption frame with:
          - Semi-transparent background pill
          - Word-by-word reveal with pop-in animation
          - Active word in gold, previous words in white
          - Emoji insertion for keywords
        Returns RGBA numpy array.
        """
        font = self._get_font(self.caption_font_size)
        img = Image.new('RGBA', (frame_w, frame_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        chunk_start = chunk['start']
        chunk_words = chunk['words']
        
        # Determine which words are visible at time t
        visible_parts = []
        for word_info in chunk_words:
            word_t = word_info['start']
            word_text = word_info['text']
            emoji = self._get_emoji_for_word(word_text)
            display_text = f"{emoji}{word_text}" if emoji else word_text

            if t >= word_t - chunk_start:
                # Word is visible
                elapsed = t - (word_t - chunk_start)
                is_active = (t - (word_t - chunk_start)) < 0.4  # Active for 400ms after appear

                # Pop scale factor (1.0 -> 1.2 -> 1.0 over 200ms)
                if elapsed < 0.2:
                    scale = 1.0 + 0.2 * math.sin(elapsed / 0.2 * math.pi)
                else:
                    scale = 1.0

                visible_parts.append({
                    "text": display_text,
                    "is_active": is_active,
                    "is_highlight": self._is_highlight_word(word_text),
                    "scale": scale,
                    "elapsed": elapsed,
                })

        if not visible_parts:
            return np.array(img)

        # Measure total text width for centering
        space_width = draw.textlength(" ", font=font)
        total_width = 0
        word_widths = []
        for part in visible_parts:
            w = draw.textlength(part["text"], font=font)
            word_widths.append(w)
            total_width += w
        total_width += space_width * (len(visible_parts) - 1)

        # Draw background pill
        pill_x1 = (frame_w - total_width) // 2 - self.pill_padding_x
        pill_y1 = self.caption_y_position - self.pill_padding_y
        pill_x2 = (frame_w + total_width) // 2 + self.pill_padding_x
        
        # Get text height for pill
        bbox = font.getbbox("Ay")
        text_height = bbox[3] - bbox[1]
        pill_y2 = self.caption_y_position + text_height + self.pill_padding_y

        # Clamp pill to frame bounds
        pill_x1 = max(10, pill_x1)
        pill_x2 = min(frame_w - 10, pill_x2)

        # Draw rounded rectangle pill background
        draw.rounded_rectangle(
            [pill_x1, pill_y1, pill_x2, pill_y2],
            radius=self.pill_corner_radius,
            fill=self.pill_bg_color
        )

        # Draw each word
        x_cursor = (frame_w - total_width) // 2
        for i, part in enumerate(visible_parts):
            # Color selection
            if part["is_highlight"] or part["is_active"]:
                fill_color = (255, 215, 0, 255)  # Gold #FFD700
            else:
                fill_color = (255, 255, 255, 255)  # White

            # Stroke (outline) for readability
            stroke_color = (0, 0, 0, 255)
            stroke_width = 4

            # Apply scale via font size adjustment (simulates pop)
            scaled_font_size = int(self.caption_font_size * part["scale"])
            scaled_font = self._get_font(scaled_font_size)

            # Vertical offset for scale animation (bounce up slightly)
            y_offset = 0
            if part["elapsed"] < 0.15:
                y_offset = int(-8 * math.sin(part["elapsed"] / 0.15 * math.pi))

            # Draw text with stroke
            text_y = self.caption_y_position + y_offset
            
            # Draw stroke (outline) by drawing text offset in all directions
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx * dx + dy * dy <= stroke_width * stroke_width:
                        draw.text((x_cursor + dx, text_y + dy), part["text"], fill=stroke_color, font=scaled_font)
            
            # Draw main text
            draw.text((x_cursor, text_y), part["text"], fill=fill_color, font=scaled_font)

            x_cursor += word_widths[i] + space_width

        return np.array(img)

    def _create_kinetic_caption_clips(self, words: List[Dict], duration: float) -> List:
        """
        Creates kinetic caption overlay as a SINGLE pre-rendered VideoClip.
        
        Optimization: Pre-computes all unique visual states (one per word reveal)
        instead of rendering PIL frames per-video-frame. This reduces render cost
        from ~25000 PIL renders to ~30 PIL renders for a 15s clip.
        """
        chunks = self._build_caption_chunks(words)
        if not chunks:
            return []

        # Height of the caption region (to avoid full-frame PIL images)
        font = self._get_font(self.caption_font_size)
        text_bbox = font.getbbox("Ay")
        text_h = text_bbox[3] - text_bbox[1]
        region_h = text_h + self.pill_padding_y * 2 + 30  # Extra padding
        region_y_start = self.caption_y_position - self.pill_padding_y - 10

        # Pre-render all unique states for each chunk
        # A state changes only when: (1) a new word appears, (2) active word changes
        # We discretize: render one frame per "word reveal" event + one with all settled
        
        chunk_frames = {}  # (chunk_idx, num_visible_words, has_active_word) -> RGBA numpy array (region-sized)
        
        for ci, chunk in enumerate(chunks):
            chunk_words = chunk['words']
            for nvis in range(1, len(chunk_words) + 1):
                for active in [True, False]:
                    key = (ci, nvis, active)
                    if key in chunk_frames:
                        continue
                    # Render this state
                    img = Image.new('RGBA', (self.width, region_h), (0, 0, 0, 0))
                    draw = ImageDraw.Draw(img)
                    
                    visible_words = chunk_words[:nvis]
                    display_texts = []
                    for w in visible_words:
                        emoji = self._get_emoji_for_word(w['text'])
                        display_texts.append(f"{emoji}{w['text']}" if emoji else w['text'])
                    
                    # Measure
                    space_w = draw.textlength(" ", font=font)
                    word_widths = [draw.textlength(dt, font=font) for dt in display_texts]
                    total_w = sum(word_widths) + space_w * (len(display_texts) - 1)
                    
                    # Draw pill background
                    pill_x1 = max(10, (self.width - total_w) // 2 - self.pill_padding_x)
                    pill_x2 = min(self.width - 10, (self.width + total_w) // 2 + self.pill_padding_x)
                    pill_y1 = 10
                    pill_y2 = region_h - 10
                    draw.rounded_rectangle(
                        [pill_x1, pill_y1, pill_x2, pill_y2],
                        radius=self.pill_corner_radius,
                        fill=self.pill_bg_color
                    )
                    
                    # Draw words
                    x_cursor = (self.width - total_w) // 2
                    text_y = self.pill_padding_y + 5
                    for i, dt in enumerate(display_texts):
                        is_last = (i == nvis - 1)
                        is_highlight = self._is_highlight_word(visible_words[i]['text'])
                        
                        if (is_last and active) or is_highlight:
                            fill = (255, 215, 0, 255)  # Gold
                        else:
                            fill = (255, 255, 255, 255)  # White
                        
                        # Use PIL built-in stroke (MUCH faster than manual loop)
                        draw.text((x_cursor, text_y), dt, fill=fill, font=font,
                                  stroke_width=3, stroke_fill=(0, 0, 0, 255))
                        x_cursor += word_widths[i] + space_w
                    
                    chunk_frames[key] = np.array(img)
        
        logger.info(f"🎬 Pre-rendered {len(chunk_frames)} unique caption states for {len(chunks)} chunks")

        # Build timeline: for each video time t, determine which pre-rendered frame to show
        fps = settings.FPS
        total_frames = int(duration * fps) + 1
        
        # Create a frame lookup function
        def get_caption_state(t):
            """Returns the key into chunk_frames for time t, or None if no caption."""
            for ci, chunk in enumerate(chunks):
                if chunk['start'] <= t < chunk['end']:
                    chunk_words = chunk['words']
                    # Count visible words
                    nvis = 0
                    latest_word_time = 0
                    for w in chunk_words:
                        if t >= w['start']:
                            nvis += 1
                            latest_word_time = w['start']
                    if nvis == 0:
                        return None
                    # Is the latest word still "active"? (within 400ms of appearance)
                    active = (t - latest_word_time) < 0.4
                    return (ci, nvis, active)
            return None

        # Build the single composite overlay clip
        def make_overlay_frame(t):
            key = get_caption_state(t)
            if key is None or key not in chunk_frames:
                # Return transparent (black with zero alpha for compositing)
                return np.zeros((region_h, self.width, 3), dtype=np.uint8)
            frame = chunk_frames[key]
            if frame.shape[2] == 4:
                alpha = frame[:, :, 3:4].astype(float) / 255.0
                rgb = frame[:, :, :3].astype(float)
                return (rgb * alpha).astype(np.uint8)
            return frame[:, :, :3]

        def make_overlay_mask(t):
            key = get_caption_state(t)
            if key is None or key not in chunk_frames:
                return np.zeros((region_h, self.width), dtype=float)
            frame = chunk_frames[key]
            if frame.shape[2] == 4:
                return frame[:, :, 3].astype(float) / 255.0
            return np.ones((region_h, self.width), dtype=float)

        clip = VideoClip(make_overlay_frame, duration=duration)
        mask = VideoClip(make_overlay_mask, ismask=True, duration=duration)
        clip = clip.set_mask(mask)
        clip = clip.set_position(('center', region_y_start))

        return [clip]

    def create_video(self, video_path: str, title: str, words: List[Dict],
                     b_roll_keyword: Optional[str] = None,
                     credit_text: Optional[str] = None,
                     video_type: str = "short") -> Optional[str]:
        """
        Creates the final short video with:
          1. Face-tracking auto-crop (16:9 → 9:16)
          2. B-Roll flash overlay (optional)
          3. Kinetic live captions with pop animation
          4. Attribution credit bar
          5. Gradient progress bar
        """
        logger.info(f"🎬 Processing Video: {video_path} (Type: {video_type})")
        clip = VideoFileClip(video_path)
        w_in, h_in = clip.size
        duration = clip.duration
        
        if video_type == "long":
            # For long videos, preserve 16:9 aspect ratio but scale to standard 1080p width
            self.width = 1920
            self.height = 1080
            # Scale down if original is larger, keep if smaller
            if w_in > self.width:
                clip = clip.resize(width=self.width)
            else:
                self.width = w_in
                self.height = h_in
            
            # Position captions at bottom center
            self.caption_y_position = int(self.height * 0.85)
            
            # Use uncropped video
            base_clip = clip
        else:
            # Shorts logic (9:16 vertical crop)
            self.width = settings.VIDEO_WIDTH # usually 1080
            self.height = settings.VIDEO_HEIGHT # usually 1920
            self.caption_y_position = int(self.height * 0.65)
            
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

        # 2. B-Roll Flash (optional)
        if b_roll_keyword:
            broll_path = str(settings.DATA_DIR / f"broll_{b_roll_keyword}.jpg")
            try:
                url = f"https://loremflickr.com/{self.width}/{self.height // 2}/{b_roll_keyword}"
                urllib.request.urlretrieve(url, broll_path)
                broll_clip = ImageClip(broll_path).resize((self.width, self.height // 2))
                broll_clip = broll_clip.set_position(('center', 'top')).set_start(0).set_duration(2.5).crossfadeout(0.5)
                clips.append(broll_clip)
            except Exception as e:
                logger.warning(f"Failed to fetch B-Roll: {e}")

        # 3. Kinetic Live Captions (the star feature)
        if words:
            logger.info("✨ Generating premium kinetic captions...")
            caption_clips = self._create_kinetic_caption_clips(words, duration)
            clips.extend(caption_clips)
        else:
            # Fallback: simple title overlay if no word timestamps (PIL-based, no ImageMagick)
            title_img_clip = self._create_pil_text_clip(
                title, fontsize=65, color=(255, 255, 255), 
                stroke_color=(0, 0, 0), stroke_width=4,
                max_width=self.width - 120, y_position=150
            )
            if title_img_clip:
                title_img_clip = title_img_clip.set_duration(duration)
                clips.append(title_img_clip)

        # 4. Attribution Credit Bar (bottom of screen, PIL-based)
        if credit_text:
            credit_img_clip = self._create_pil_text_clip(
                f"Credit: {credit_text}", fontsize=30, color=(200, 200, 200),
                stroke_color=(0, 0, 0), stroke_width=2,
                max_width=self.width - 60, y_position=self.height - 70
            )
            if credit_img_clip:
                credit_img_clip = credit_img_clip.set_duration(duration)
                clips.append(credit_img_clip)

        # 5. Gradient Progress Bar
        bar_h = 8
        def make_progress(t):
            prog = t / max(duration, 0.1)
            f = np.zeros((bar_h, self.width, 3), dtype=np.uint8)
            bar_width = int(self.width * prog)
            if bar_width > 0:
                # Gradient from cyan to green
                for x in range(bar_width):
                    ratio = x / max(self.width, 1)
                    r = int(0 * (1 - ratio) + 0 * ratio)
                    g = int(255 * (1 - ratio) + 255 * ratio)
                    b = int(255 * (1 - ratio) + 136 * ratio)
                    f[:, x] = [r, g, b]
            return f

        progress_clip = VideoClip(make_progress, duration=duration).set_position(('center', self.height - bar_h - 15))
        clips.append(progress_clip)

        # Composite & Render
        output_path = str(settings.OUTPUT_DIR / f"final_short_{os.path.basename(video_path)}")
        logger.info(f"🎥 Rendering: {output_path}")

        final_video = CompositeVideoClip(clips, size=(self.width, self.height))
        final_video.write_videofile(
            output_path,
            fps=settings.FPS,
            codec='libx264',
            audio_codec='aac',
            bitrate="8000k",        # High bitrate for 1080p
            audio_bitrate="192k",   # Crisp audio
            preset='fast',          # Fast export but retains quality with the high bitrate
            threads=4
        )

        logger.info("✅ Rendering Complete.")
        return output_path


video_service = VideoService()
