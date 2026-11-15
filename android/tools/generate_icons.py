#!/usr/bin/env python3
"""Draw the legacy launcher icons: two chat bubbles and the letters CC."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "res"
BG = (18, 53, 47, 255)
CREAM = (244, 233, 212, 255)
GREEN = (61, 220, 151, 255)
INK = (16, 36, 28, 255)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def bubble(draw, box, fill, tail):
    draw.rounded_rectangle(box, radius=int((box[2] - box[0]) * 0.28), fill=fill)
    draw.polygon(tail, fill=fill)


def render(size):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(size * 0.22)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BG)
    s = size / 108

    def p(x, y):
        return (x * s, y * s)

    bubble(
        draw,
        (*p(50, 26), *p(92, 60)),
        CREAM,
        [p(74, 56), p(88, 70), p(68, 58)],
    )
    bubble(
        draw,
        (*p(16, 46), *p(68, 84)),
        GREEN,
        [p(30, 78), p(16, 94), p(40, 82)],
    )
    font = ImageFont.truetype(FONT, int(size * 0.22))
    draw.text(p(62, 30), "C", font=font, fill=INK)
    draw.text(p(30, 52), "C", font=font, fill=INK)
    return image


def circle(image):
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, image.size[0] - 1, image.size[1] - 1), fill=255)
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image, mask=mask)
    return out


def main():
    master = render(512)
    preview = ROOT.parents[4] / "icon-preview.png"
    # preview is written next to the tool for a visual check, not into res/
    master.save("/tmp/chatclumer-icon-preview.png")
    densities = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    for folder, size in densities.items():
        dest = ROOT / folder
        dest.mkdir(parents=True, exist_ok=True)
        icon = master.resize((size, size), Image.Resampling.LANCZOS)
        icon.save(dest / "ic_launcher.png")
        circle(icon).save(dest / "ic_launcher_round.png")
    print("wrote launcher icons")


if __name__ == "__main__":
    main()
