#!/usr/bin/env python3
"""Regenerate frontend/public/og-image.png — the link-preview card.

    python3 tools/make-og-image.py

Two things about this image are deliberate and easy to undo by accident:

OPAQUE BACKGROUND. It used to be favicon-192x192.png, which is transparent.
iMessage fills a transparent card by sampling a colour out of the image, and
what it picked was the clay of the dot — so the logo sat on a background
almost exactly its own colour. Any replacement must stay opaque.

192 PIXELS. WhatsApp gives an image about 300px or larger on both sides the
full-width banner treatment; below that it renders the compact thumbnail
beside the title, which is the card we want. Making this bigger would look
crisper in iMessage (which upscales it) at the cost of WhatsApp's layout.

Geometry AND colour are favicon.svg's, on its 32-unit box: outer ring r=14 in
clay at 28% opacity, inner dot r=8 in solid clay. Composited over the green
rather than recoloured, so the card is the site's own mark on a green ground.
A version with the ring recoloured into the green family was tried and
rejected by the owner — the ring is orange.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "frontend/public/og-image.png"

SIZE, SUPERSAMPLE = 192, 4          # drawn 4x, downsampled: smooth circle edges
BG = (27, 67, 50)                   # --green-800 #1b4332
CLAY = (201, 120, 58)               # --clay-500  #c9783a
RING_ALPHA = 71                     # 0.28, the favicon's own ring opacity


def main() -> None:
    w = SIZE * SUPERSAMPLE
    base = Image.new("RGBA", (w, w), BG + (255,))
    # The circles go on their own layer so the ring's alpha composites against
    # the green, exactly as the favicon's does against the page.
    marks = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(marks)
    c = w / 2
    for radius, alpha in ((c * (14 / 16), RING_ALPHA), (c * (8 / 16), 255)):
        d.ellipse([c - radius, c - radius, c + radius, c + radius],
                  fill=CLAY + (alpha,))
    im = Image.alpha_composite(base, marks).convert("RGB")
    im.resize((SIZE, SIZE), Image.LANCZOS).save(OUT, optimize=True)
    print(f"wrote {OUT} ({SIZE}x{SIZE}, opaque)")


if __name__ == "__main__":
    main()
