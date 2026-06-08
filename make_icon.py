"""Generate claude-usage.ico — run once to create the icon file."""
import math
from pathlib import Path
from PIL import Image, ImageDraw


def make_frame(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    p      = max(1, round(size * 0.055))
    corner = round(size * 0.24)

    d.rounded_rectangle(
        [p, p, size - p - 1, size - p - 1],
        radius=corner,
        fill=(14, 14, 20, 255),
        outline=(40, 40, 56, 255),
        width=max(1, size // 40),
    )

    cx  = size * 0.50
    cy  = size * 0.44
    R   = size * 0.27
    lw  = max(2, round(size * 0.11))
    gap = 36

    d.arc([cx - R, cy - R, cx + R, cy + R],
          start=gap, end=360 - gap,
          fill=(212, 149, 106, 255), width=lw)

    for angle_deg in (gap, 360 - gap):
        rad = math.radians(angle_deg)
        ex, ey = cx + R * math.cos(rad), cy + R * math.sin(rad)
        r = lw / 2
        d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(212, 149, 106, 255))

    bx1, bx2 = size * 0.20, size * 0.80
    by  = size * 0.76
    bh  = max(2, round(size * 0.07))
    br  = bh // 2

    d.rounded_rectangle([bx1, by, bx2, by + bh], radius=br, fill=(255, 255, 255, 35))
    d.rounded_rectangle(
        [bx1, by, bx1 + (bx2 - bx1) * 0.35, by + bh],
        radius=br, fill=(95, 211, 141, 255),
    )

    return img


if __name__ == "__main__":
    out = Path(__file__).parent / "claude-usage.ico"
    img = make_frame(256).convert("RGBA")
    img.save(
        out,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
    )
    print(f"Saved: {out}  ({out.stat().st_size:,} bytes)")
