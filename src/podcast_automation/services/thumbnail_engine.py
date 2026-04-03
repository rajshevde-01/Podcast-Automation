import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Optional
from loguru import logger
from ..config import settings

class ThumbnailService:
    def __init__(self, width: int = settings.VIDEO_WIDTH, height: int = settings.VIDEO_HEIGHT):
        self.width = width
        self.height = height

    def _get_font(self, size: int) -> ImageFont:
        try:
            return ImageFont.truetype("arialbd.ttf", size)
        except IOError:
            return ImageFont.load_default()

    def create_thumbnail(self, title: str, episode_id: str, theme_color: tuple = (0, 255, 136)) -> Optional[str]:
        output_file = str(settings.OUTPUT_DIR / f"thumb_{episode_id}.jpg")
        logger.info(f"Generating Thumbnail: {output_file}")
        
        img = Image.new('RGB', (self.width, self.height), (15, 15, 20))
        draw = ImageDraw.Draw(img)
        
        # 1. Gradient Glow
        for y in range(self.height):
            alpha = max(0, 1 - (y / self.height) ** 1.5)
            r = int(theme_color[0] * alpha * 0.4)
            g = int(theme_color[1] * alpha * 0.4)
            b = int(theme_color[2] * alpha * 0.4)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
            
        # 2. Add Podcast Badge
        badge_text = "PODCAST CLIP"
        font_badge = self._get_font(60)
        badge_bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
        bw = badge_bbox[2] - badge_bbox[0]
        bh = badge_bbox[3] - badge_bbox[1]
        
        pad = 30
        badge_x = (self.width - bw) // 2
        badge_y = 100
        draw.rectangle([badge_x - pad, badge_y - pad, badge_x + bw + pad, badge_y + bh + pad], fill=theme_color, outline='white', width=6)
        draw.text((badge_x, badge_y), badge_text, fill='black', font=font_badge)

        # 3. Main Text (Wrapped)
        font_large = self._get_font(140)
        words = title.upper().split()
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            bbox = draw.textbbox((0, 0), " ".join(current_line), font=font_large)
            if bbox[2] > self.width - 150:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
            
        text_y = int(self.height * 0.6)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font_large)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            
            draw.text(((self.width - text_w)//2 + 8, text_y + 8), line, fill='black', font=font_large)
            draw.text(((self.width - text_w)//2, text_y), line, fill='white', font=font_large)
            text_y += text_h + 30
            
        # Border
        draw.rectangle([0, 0, self.width-1, self.height-1], outline=theme_color, width=25)
        
        img.save(output_file, quality=95)
        logger.info(f"✅ Thumbnail Saved.")
        return output_file

thumbnail_service = ThumbnailService()
