"""
make_icon.py — Generate icon.ico for CrinkleDen
================================================
Creates a multi-resolution Windows icon file containing:
  256x256, 128x128, 64x64, 48x48, 32x32, 16x16

Requires Pillow (installed automatically by build.py --install-deps).
Run standalone:  python make_icon.py

The generated icon.ico is picked up by build.py automatically.
"""

from pathlib import Path

ICON_OUT = Path(__file__).parent / "icon.ico"

# Colour palette (matches the app's CrinkleDen theme)
BG       = (7,   16,  31)    # #07101f  — deep midnight navy
PANEL    = (12,  26,  48)    # #0c1a30
AMBER    = (245, 166, 35)    # #f5a623
TEAL     = (62,  207, 191)   # #3ecfbf
PINK     = (255, 121, 176)   # #ff79b0
WHITE    = (228, 238, 248)   # #e4eef8


def make_icon():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed. Run: pip install Pillow")
        print("Or: python build.py --install-deps")
        raise

    sizes = [256, 128, 64, 48, 32, 16]
    frames = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        pad = max(2, size // 16)
        r   = size // 2 - pad          # outer radius
        cx  = size // 2
        cy  = size // 2

        # Background circle
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(*PANEL, 255),
            outline=(*AMBER, 255),
            width=max(1, size // 32),
        )

        # Inner decorative ring (teal)
        r2 = int(r * 0.82)
        draw.ellipse(
            [cx - r2, cy - r2, cx + r2, cy + r2],
            fill=None,
            outline=(*TEAL, 180),
            width=max(1, size // 48),
        )

        # Draw a stylised "A" (ABDL) letter in the centre
        if size >= 32:
            font_size = max(8, int(size * 0.45))
            # Try system fonts, fall back to default
            font = None
            for fname in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf",
                          "DejaVuSans.ttf", "LiberationSans-Bold.ttf"):
                try:
                    font = ImageFont.truetype(fname, font_size)
                    break
                except (IOError, OSError):
                    continue
            if font is None:
                font = ImageFont.load_default()

            text = "A"
            # Get bounding box
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw   = bbox[2] - bbox[0]
                th   = bbox[3] - bbox[1]
            except AttributeError:
                tw, th = draw.textsize(text, font=font)

            tx = cx - tw // 2
            ty = cy - th // 2 - max(1, size // 32)

            # Drop shadow
            shadow_off = max(1, size // 64)
            draw.text((tx + shadow_off, ty + shadow_off), text,
                      fill=(*BG, 180), font=font)
            # Main letter
            draw.text((tx, ty), text, fill=(*AMBER, 255), font=font)

        # Small dots at cardinal points (decorative, sizes >= 48 only)
        if size >= 48:
            dot_r = max(2, size // 24)
            for dx, dy in [(0, -(r - 2)), (0, r - 2), (-(r-2), 0), (r-2, 0)]:
                draw.ellipse(
                    [cx+dx-dot_r, cy+dy-dot_r, cx+dx+dot_r, cy+dy+dot_r],
                    fill=(*PINK, 220),
                )

        frames.append(img)

    # Save as multi-resolution .ico
    frames[0].save(
        ICON_OUT,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"✓ Icon written: {ICON_OUT}  ({ICON_OUT.stat().st_size // 1024} KB)")
    return ICON_OUT


if __name__ == "__main__":
    make_icon()
