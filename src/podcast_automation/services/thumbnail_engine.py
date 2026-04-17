import os
import io
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Optional
from loguru import logger
from ..config import settings

class ThumbnailService:
    def __init__(self, width: int = settings.VIDEO_WIDTH, height: int = settings.VIDEO_HEIGHT):
        self.width = width
        self.height = height

    def _get_font(self, size: int) -> ImageFont:
        for font_name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "FreeSansBold.ttf"):
            try:
                return ImageFont.truetype(font_name, size)
            except IOError:
                continue
        return ImageFont.load_default()

    # ------------------------------------------------------------------
    # Face frame background
    # ------------------------------------------------------------------

    def _face_frame_to_background(self, face_frame_bgr) -> Optional[Image.Image]:
        """
        Convert an OpenCV BGR face frame to a blurred PIL Image scaled to
        full thumbnail size (used as the background instead of a plain gradient).
        """
        try:
            import cv2
            import numpy as np
            frame_rgb = cv2.cvtColor(face_frame_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(frame_rgb)
            pil_img = pil_img.resize((self.width, self.height), Image.LANCZOS)
            # Darken so the text is still legible
            overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 140))
            pil_img = pil_img.convert("RGBA")
            pil_img = Image.alpha_composite(pil_img, overlay).convert("RGB")
            return pil_img
        except Exception as e:
            logger.warning(f"face_frame_to_background failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Podcast logo overlay
    # ------------------------------------------------------------------

    def _fetch_podcast_logo(self, channel_id: Optional[str]) -> Optional[Image.Image]:
        """
        Download the podcast channel avatar from YouTube Data API and return
        it as a small circular PIL Image (200×200).
        """
        if not channel_id or not settings.YOUTUBE_API_KEY:
            return None
        try:
            url = "https://www.googleapis.com/youtube/v3/channels"
            params = {
                "part": "snippet",
                "id": channel_id,
                "key": settings.YOUTUBE_API_KEY,
            }
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                return None
            thumbnail_url = (
                items[0]
                .get("snippet", {})
                .get("thumbnails", {})
                .get("high", {})
                .get("url")
            )
            if not thumbnail_url:
                return None
            img_resp = requests.get(thumbnail_url, timeout=8)
            img_resp.raise_for_status()
            logo = Image.open(io.BytesIO(img_resp.content)).convert("RGBA")
            logo = logo.resize((180, 180), Image.LANCZOS)

            # Circular mask
            mask = Image.new("L", (180, 180), 0)
            from PIL import ImageDraw as _ID
            _ID.Draw(mask).ellipse((0, 0, 180, 180), fill=255)
            logo.putalpha(mask)
            return logo
        except Exception as e:
            logger.warning(f"Podcast logo fetch failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Main create_thumbnail entry point
    # ------------------------------------------------------------------

    def create_thumbnail(
        self,
        title: str,
        episode_id: str,
        theme_color: tuple = (0, 255, 136),
        face_frame_bgr=None,
        channel_id: Optional[str] = None,
    ) -> Optional[str]:
        output_file = str(settings.OUTPUT_DIR / f"thumb_{episode_id}.jpg")
        logger.info(f"Generating Thumbnail: {output_file}")

        # --- Background ---
        if face_frame_bgr is not None:
            bg = self._face_frame_to_background(face_frame_bgr)
        else:
            bg = None

        if bg is None:
            # Fallback: gradient on dark canvas
            bg = Image.new("RGB", (self.width, self.height), (15, 15, 20))
            draw_bg = ImageDraw.Draw(bg)
            for y in range(self.height):
                alpha = max(0, 1 - (y / self.height) ** 1.5)
                r = int(theme_color[0] * alpha * 0.4)
                g = int(theme_color[1] * alpha * 0.4)
                b = int(theme_color[2] * alpha * 0.4)
                draw_bg.line([(0, y), (self.width, y)], fill=(r, g, b))

        img = bg.copy()
        draw = ImageDraw.Draw(img)

        # --- Podcast Badge ---
        badge_text = "PODCAST CLIP"
        font_badge = self._get_font(60)
        badge_bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
        bw = badge_bbox[2] - badge_bbox[0]
        bh = badge_bbox[3] - badge_bbox[1]
        pad = 30
        badge_x = (self.width - bw) // 2
        badge_y = 100
        draw.rectangle(
            [badge_x - pad, badge_y - pad, badge_x + bw + pad, badge_y + bh + pad],
            fill=theme_color,
            outline="white",
            width=6,
        )
        draw.text((badge_x, badge_y), badge_text, fill="black", font=font_badge)

        # --- Main Title Text ---
        font_large = self._get_font(130)
        words = title.upper().split()
        lines = []
        current_line: list = []
        for word in words:
            current_line.append(word)
            bbox = draw.textbbox((0, 0), " ".join(current_line), font=font_large)
            if bbox[2] > self.width - 150:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))

        text_y = int(self.height * 0.58)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font_large)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            # Shadow
            draw.text(((self.width - tw) // 2 + 6, text_y + 6), line, fill="black", font=font_large)
            draw.text(((self.width - tw) // 2, text_y), line, fill="white", font=font_large)
            text_y += th + 28

        # --- Coloured border ---
        draw.rectangle([0, 0, self.width - 1, self.height - 1], outline=theme_color, width=22)

        # --- Podcast logo (bottom-right) ---
        logo = self._fetch_podcast_logo(channel_id)
        if logo:
            logo_x = self.width - 180 - 30
            logo_y = self.height - 180 - 30
            img.paste(logo, (logo_x, logo_y), logo)

        img.save(output_file, quality=95)
        logger.info("✅ Thumbnail Saved.")
        return output_file


thumbnail_service = ThumbnailService()
