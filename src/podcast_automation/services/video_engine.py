import os
import math
import numpy as np
import urllib.request
import random
from typing import List, Dict, Optional
from loguru import logger
from moviepy.editor import (
    VideoFileClip, TextClip, CompositeVideoClip,
    ImageClip, ColorClip, VideoClip, concatenate_videoclips,
)
from ..config import settings

# MediaPipe face detection — graceful fallback to OpenCV if unavailable
try:
    import mediapipe as mp
    _mp_face = mp.solutions.face_detection
    _MEDIAPIPE_OK = True
except Exception:
    _MEDIAPIPE_OK = False
    import cv2 as _cv2

# OpenCV always available (needed for frame sampling)
import cv2


class VideoService:
    def __init__(self, width: int = settings.VIDEO_WIDTH, height: int = settings.VIDEO_HEIGHT):
        self.width = width
        self.height = height
        # Haar cascade kept as last-resort fallback
        self._haar = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

    # ------------------------------------------------------------------
    # Face detection helpers
    # ------------------------------------------------------------------

    def _get_face_center_x_mediapipe(self, frame_rgb) -> Optional[int]:
        """Use MediaPipe FaceDetection for accurate, rotation-aware face tracking."""
        try:
            with _mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5) as detector:
                results = detector.process(frame_rgb)
            if not results.detections:
                return None
            # Pick the detection with the highest confidence
            best = max(results.detections, key=lambda d: d.score[0])
            bbox = best.location_data.relative_bounding_box
            h, w = frame_rgb.shape[:2]
            cx = int((bbox.xmin + bbox.width / 2) * w)
            return cx
        except Exception:
            return None

    def _get_face_center_x_haar(self, frame_bgr) -> Optional[int]:
        """Haar cascade fallback."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = self._haar.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return x + w // 2

    def _get_face_center_x(self, frame_bgr) -> Optional[int]:
        if _MEDIAPIPE_OK:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            cx = self._get_face_center_x_mediapipe(frame_rgb)
            if cx is not None:
                return cx
        return self._get_face_center_x_haar(frame_bgr)

    # ------------------------------------------------------------------
    # Best face frame extraction (for thumbnail)
    # ------------------------------------------------------------------

    def extract_best_face_frame(self, video_path: str, num_samples: int = 20) -> Optional[np.ndarray]:
        """
        Sample *num_samples* frames from the video and return the BGR frame
        that contains the largest / most-confident face.
        Returns None if no face is found.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames < 1:
            cap.release()
            return None

        best_frame = None
        best_score = -1.0

        step = max(1, total_frames // num_samples)
        for i in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                continue

            if _MEDIAPIPE_OK:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                try:
                    with _mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.4) as det:
                        results = det.process(frame_rgb)
                    if results.detections:
                        score = max(d.score[0] for d in results.detections)
                        if score > best_score:
                            best_score = score
                            best_frame = frame.copy()
                except Exception:
                    pass
            else:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self._haar.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
                if len(faces) > 0:
                    area = max(w * h for _, _, w, h in faces)
                    if area > best_score:
                        best_score = float(area)
                        best_frame = frame.copy()

        cap.release()
        return best_frame  # None if no face ever detected

    # ------------------------------------------------------------------
    # Karaoke subtitle builder
    # ------------------------------------------------------------------

    def _build_karaoke_clips(self, words: List[Dict]) -> List[TextClip]:
        """
        Build word-by-word karaoke subtitle clips.

        Each word gets its own TextClip where the current word is rendered in
        yellow and shown at the subtitle position; surrounding words (±2) are
        shown in white to provide context.  This is the viral "word-pop" style
        seen on most trending Shorts / Reels.
        """
        if not words:
            return []

        clips = []
        n = len(words)

        for idx, word in enumerate(words):
            start_t = word.get("start", 0)
            end_t = word.get("end", start_t + 0.3)
            if end_t <= start_t:
                end_t = start_t + 0.3

            # Build context window: up to 3 words before + current + up to 2 after
            ctx_start = max(0, idx - 3)
            ctx_end = min(n, idx + 3)
            context_words = words[ctx_start:ctx_end]
            current_pos = idx - ctx_start

            # Build coloured text: current word uppercase+yellow, rest white+small
            parts = []
            for i, w in enumerate(context_words):
                if i == current_pos:
                    parts.append(f"[{w['text'].upper()}]")
                else:
                    parts.append(w["text"])
            display_text = " ".join(parts)

            # Scale-up/bounce: start at 90% scale, pop to 105% then settle to 100%
            duration = max(end_t - start_t, 0.1)

            def make_scale(dur=duration):
                def scale_fn(t):
                    progress = t / dur
                    if progress < 0.15:
                        return 0.90 + 0.15 * (progress / 0.15)
                    elif progress < 0.35:
                        return 1.05 - 0.05 * ((progress - 0.15) / 0.20)
                    else:
                        return 1.0
                return scale_fn

            try:
                txt = TextClip(
                    display_text,
                    fontsize=88,
                    color="yellow",
                    font="Arial-Bold",
                    stroke_color="black",
                    stroke_width=5,
                    method="caption",
                    align="center",
                    size=(self.width - 120, None),
                ).set_position(("center", self.height // 2 + 80)) \
                 .set_start(start_t) \
                 .set_duration(duration) \
                 .resize(make_scale())
                clips.append(txt)
            except Exception as e:
                logger.debug(f"Karaoke clip error at word '{word.get('text')}': {e}")

        return clips

    # ------------------------------------------------------------------
    # Main create_video entry point
    # ------------------------------------------------------------------

    def create_video(
        self,
        video_path: str,
        title: str,
        words: List[Dict],
        b_roll_keyword: Optional[str] = None,
    ) -> Optional[str]:
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
            cropped = frame[:, x1: x1 + crop_w]
            return cv2.resize(cropped, (self.width, self.height))

        # 1. Base Clip (auto-crop with smooth MediaPipe face tracking)
        base_clip = clip.fl(auto_crop_frame)
        clips = [base_clip]

        # 2. B-Roll Flash (2.5s at the top of the screen)
        if b_roll_keyword:
            broll_path = str(settings.DATA_DIR / f"broll_{b_roll_keyword}.jpg")
            try:
                url = f"https://loremflickr.com/{self.width}/{self.height // 2}/{b_roll_keyword}"
                urllib.request.urlretrieve(url, broll_path)
                broll_clip = (
                    ImageClip(broll_path)
                    .resize((self.width, self.height // 2))
                    .set_position(("center", "top"))
                    .set_start(0)
                    .set_duration(2.5)
                    .crossfadeout(0.5)
                )
                clips.append(broll_clip)
            except Exception as e:
                logger.warning(f"Failed to fetch B-Roll: {e}")

        # 3. Title at top (semi-transparent backing for legibility)
        title_bg = ColorClip(
            size=(self.width, 220), color=(0, 0, 0)
        ).set_opacity(0.55).set_position(("center", 80)).set_duration(duration)
        clips.append(title_bg)

        title_clip = TextClip(
            title,
            fontsize=62,
            color="white",
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=3,
            method="caption",
            size=(self.width - 80, None),
        ).set_position(("center", 100)).set_duration(duration)
        clips.append(title_clip)

        # 4. Word-by-word karaoke subtitles
        logger.info("Generating karaoke subtitles…")
        karaoke_clips = self._build_karaoke_clips(words)
        clips.extend(karaoke_clips)
        logger.info(f"  → {len(karaoke_clips)} word clips generated.")

        # 5. Progress bar at the bottom
        bar_h = 10

        def make_progress(t):
            prog = t / max(duration, 0.1)
            f = np.zeros((bar_h, self.width, 3), dtype=np.uint8)
            f[:, : int(self.width * prog)] = [0, 255, 136]
            return f

        progress_clip = VideoClip(make_progress, duration=duration).set_position(
            ("center", self.height - bar_h - 10)
        )
        clips.append(progress_clip)

        # Composite & Render
        output_path = str(
            settings.OUTPUT_DIR / f"final_short_{os.path.basename(video_path)}"
        )
        logger.info(f"Rendering: {output_path}")
        final_video = CompositeVideoClip(clips, size=(self.width, self.height))
        final_video.write_videofile(
            output_path,
            fps=settings.FPS,
            codec="libx264",
            audio_codec="aac",
            preset="fast",
            threads=4,
        )

        logger.info("✅ Rendering Complete.")
        return output_path


video_service = VideoService()
