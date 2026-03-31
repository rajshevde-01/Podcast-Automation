import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_thumbnail(title: str, output_file="thumbnail.jpg", theme_color=(0, 255, 136)):
    """
    Generates a vertical 9:16 thumbnail for YouTube Shorts.
    Utilizes a bold vibrant gradient and large clickbait text.
    """
    W, H = 1080, 1920
    
    # Base canvas
    img = Image.new('RGB', (W, H), (15, 15, 20))
    draw = ImageDraw.Draw(img)
    
    # 1. Background Gradient Glow (mimicking the cyber project)
    for y in range(H):
        alpha = max(0, 1 - (y / H) ** 1.5)
        r = int(theme_color[0] * alpha * 0.4)
        g = int(theme_color[1] * alpha * 0.4)
        b = int(theme_color[2] * alpha * 0.4)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
        
    # 2. Add Podcast Mic/Vibe generic graphic if available, else just a spotlight
    center_y = int(H * 0.45)
    for r in range(400, 0, -10):
        opacity = int(255 * (r / 400.0))
        c = (theme_color[0], theme_color[1], theme_color[2], opacity)
        draw.ellipse([W//2 - r, center_y - r, W//2 + r, center_y + r], outline=c, width=2)
        
    # 3. Main Text (Massive and Centered)
    try:
        font_large = ImageFont.truetype("arialbd.ttf", 140)
        font_badge = ImageFont.truetype("arialbd.ttf", 60)
    except IOError:
        font_large = ImageFont.load_default()
        font_badge = ImageFont.load_default()
        
    # Helper to wrap text
    words = title.upper().split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        # Check text length
        text_bbox = draw.textbbox((0,0), " ".join(current_line), font=font_large)
        if text_bbox[2] > W - 150:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
        
    # Draw Lines
    text_y = int(H * 0.6)
    for line in lines:
        text_bbox = draw.textbbox((0,0), line, font=font_large)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        
        # Draw Drop Shadow
        draw.text(((W - text_w)//2 + 8, text_y + 8), line, fill='black', font=font_large)
        # Draw Text
        draw.text(((W - text_w)//2, text_y), line, fill='white', font=font_large)
        
        text_y += text_h + 30
        
    # 4. Top 'NEW EPISODE' Badge
    badge_text = "PODCAST CLIP"
    badge_bbox = draw.textbbox((0,0), badge_text, font=font_badge)
    bw = badge_bbox[2] - badge_bbox[0]
    bh = badge_bbox[3] - badge_bbox[1]
    
    pad = 30
    badge_x = (W - bw) // 2
    badge_y = 100
    draw.rectangle([badge_x - pad, badge_y - pad, badge_x + bw + pad, badge_y + bh + pad], fill=theme_color, outline='white', width=6)
    draw.text((badge_x, badge_y), badge_text, fill='black', font=font_badge)
    
    # 5. Border
    draw.rectangle([0, 0, W-1, H-1], outline=theme_color, width=25)
    
    # Save
    img.save(output_file, quality=95)
    print(f"Thumbnail saved to {output_file}")
    return output_file

if __name__ == "__main__":
    create_thumbnail("THIS MAN IS CRAZY!")
