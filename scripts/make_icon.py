#!/usr/bin/env python3
"""Generate macOS .icns and Windows .ico app icons.

The icon is built from the Geneva Disease Dynamics antibody/curve motif on an
**icddr,b ochre** background, with a "Bangladesh NSL" wordmark shown at the
larger sizes (it is omitted below 128 px, where text would be illegible). The
white motif is lifted out of the source logo (white foreground on the old pink
background) so we can recolour the background freely.
"""

import platform
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
LOGO_SRC = PROJECT_ROOT / "assets" / "gdd_antibody_square_tighter.png"
OUTPUT_ICNS = PROJECT_ROOT / "assets" / "app_icon.icns"
OUTPUT_ICO = PROJECT_ROOT / "assets" / "app_icon.ico"

# --- Branding ---------------------------------------------------------------
OCHRE = (198, 122, 40)         # #C67A28 — single icddr,b-style warm ochre
ICON_TEXT = "BANGLADESH NSL"   # Helvetica-style caps wordmark (Bold)
TEXT_MIN_SIZE = 128            # only draw the wordmark at/above this pixel size
MOTIF_FILL = 0.80             # motif size as a fraction of the available area
MOTIF_NUDGE_FRAC = 0.035      # shift the motif down toward the text (frac of size)

# Bundled first (reproducible on any CI runner), then OS fallbacks.
# URW Gothic is the redistributable Century Gothic / Avant Garde equivalent.
FONT_CANDIDATES = [
    PROJECT_ROOT / "assets" / "fonts" / "URWGothic-Demi.otf",
    PROJECT_ROOT / "assets" / "fonts" / "Poppins-Bold.ttf",
    PROJECT_ROOT / "assets" / "fonts" / "NimbusSans-Bold.otf",
    PROJECT_ROOT / "assets" / "fonts" / "LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for cand in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(str(cand), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _motif_alpha(logo: Image.Image) -> Image.Image:
    """Extract the white motif from the source logo as an L-mode alpha mask.

    The source is a white motif on a coloured (pink) square, so the per-pixel
    minimum channel separates white (~255) from the coloured background (~40),
    with a smooth ramp that preserves the antialiased edges.
    """
    arr = np.asarray(logo.convert("RGB")).astype(float)
    minc = arr.min(axis=2)
    alpha = np.clip((minc - 110) / 150.0, 0.0, 1.0)
    mask = Image.fromarray((alpha * 255).astype("uint8"), "L")
    # Crop to the motif's true bounding box so the source's large internal
    # padding doesn't shrink it on the icon (its real aspect ratio is kept).
    bbox = mask.getbbox()
    return mask.crop(bbox) if bbox else mask


def _ochre_bg(size: int) -> Image.Image:
    """Solid single-colour ochre square."""
    return Image.new("RGBA", (size, size), (*OCHRE, 255))


def render_icon(motif: Image.Image, size: int) -> Image.Image:
    """Compose one square icon at the given pixel size.

    Layout: a Bold-caps wordmark across the **bottom** (only at ≥
    ``TEXT_MIN_SIZE``) directly on the single ochre background — no band — with
    the white motif filling the area above it.
    """
    canvas = _ochre_bg(size)
    draw_text = size >= TEXT_MIN_SIZE
    text_frac = 0.20 if draw_text else 0.0
    th = int(size * text_frac)
    avail_h = size - th  # region above the text for the motif

    # White motif, scaled at its native aspect ratio, centred above the text.
    cw, ch = motif.size
    scale = min(size * MOTIF_FILL / cw, avail_h * MOTIF_FILL / ch)
    nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
    mo = motif.resize((nw, nh), Image.LANCZOS)
    white = Image.new("RGBA", (nw, nh), (255, 255, 255, 255))
    white.putalpha(mo)
    mx = (size - nw) // 2
    # Centre in the area above the text, then nudge slightly down toward it.
    my = (avail_h - nh) // 2 + (int(size * MOTIF_NUDGE_FRAC) if draw_text else 0)
    canvas.alpha_composite(white, (mx, my))

    if draw_text:
        d = ImageDraw.Draw(canvas)
        fs = int(th * 0.5)
        font = _load_font(fs)
        while d.textlength(ICON_TEXT, font=font) > size * 0.9 and fs > 8:
            fs -= 2
            font = _load_font(fs)
        w = d.textlength(ICON_TEXT, font=font)
        y = size - th + (th - fs) / 2 - fs * 0.10
        d.text(((size - w) / 2, y), ICON_TEXT, font=font, fill=(255, 255, 255, 255))
    return canvas


def main():
    OUTPUT_ICNS.parent.mkdir(parents=True, exist_ok=True)

    logo = Image.open(LOGO_SRC).convert("RGBA")
    motif = _motif_alpha(logo)
    print(f"Source logo: {LOGO_SRC} ({logo.width}x{logo.height})")

    # macOS iconset requires these sizes (name -> pixel size)
    icon_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset_dir = Path(tmpdir) / "app_icon.iconset"
        iconset_dir.mkdir()

        for name, size in icon_sizes.items():
            render_icon(motif, size).save(iconset_dir / name, "PNG")
            print(f"  Created {name} ({size}x{size})")

        # Convert to .icns using macOS iconutil (only available on macOS)
        if platform.system() == "Darwin":
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(OUTPUT_ICNS)],
                check=True,
            )
            print(f"\nmacOS icon saved to: {OUTPUT_ICNS}")
        else:
            print("\nSkipping .icns generation (not on macOS)")

    # Windows .ico (sizes: 16, 32, 48, 64, 128, 256)
    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_images = [render_icon(motif, s) for s in ico_sizes]
    ico_images[0].save(
        OUTPUT_ICO,
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=ico_images[1:],
    )
    print(f"Windows icon saved to: {OUTPUT_ICO}")


if __name__ == "__main__":
    main()
