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

The geometry is favicon.svg's, on its 32-unit box: outer ring r=14, inner dot
r=8. The ring is GREEN here rather than the favicon's 28%-opacity clay —
over a green background that mix reads as muddy olive, and the whole point of
this card is that the clay dot should be the only warm thing on it.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "frontend/public/og-image.png"

SIZE, SUPERSAMPLE = 192, 4          # drawn 4x, downsampled: smooth circle edges
BG = (27, 67, 50)                   # --green-800 #1b4332
RING = (45, 106, 79)                # --green-600 #2d6a4f
CLAY = (201, 120, 58)               # --clay-500  #c9783a


def main() -> None:
    w = SIZE * SUPERSAMPLE
    im = Image.new("RGB", (w, w), BG)
    d = ImageDraw.Draw(im)
    c = w / 2
    for radius, fill in ((c * (14 / 16), RING), (c * (8 / 16), CLAY)):
        d.ellipse([c - radius, c - radius, c + radius, c + radius], fill=fill)
    im.resize((SIZE, SIZE), Image.LANCZOS).save(OUT, optimize=True)
    print(f"wrote {OUT} ({SIZE}x{SIZE}, opaque)")


if __name__ == "__main__":
    main()
