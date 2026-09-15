"""
Strip the WTA tier tags down to their lettering.

The tags ship as opaque rounded rectangles — purple for 250, teal for 500,
gold for 1000 — with the wordmark and the number knocked out in white. The
dashboard now paints the tour's own colour behind every tier stamp (the plate
that replaced the ATP/WTA pill), and the tag's baked-in tier colour was the one
thing left on the card arguing with it.

What comes out is the lettering alone: the artwork's off-white, with alpha set
to how much of each pixel the letters covered, so the plate colour shows
through from underneath and lives in theme.js rather than in a PNG.

ON THE SAME CANVAS, deliberately. TierBadge scales the whole frame to fit its
box, so cropping to the lettering would enlarge the wordmark relative to the
ATP stamps beside it — the tag's own margin is what keeps the two tours the
same size.

The tier colour is read from the art, not typed in: every one of these files is
a flat fill, and a hard-coded triple is a silent wrong answer the day the
artwork is redrawn.

    python3 gen-tour-tag-plates.py
"""
from collections import Counter
from pathlib import Path

from PIL import Image

ART = Path(__file__).parent.parent / 'mobile' / 'assets' / 'logos'
# The TIER tags only. The ATP stamps are already drawn on transparency, and the
# slam crests are left exactly as their tournaments draw them — the WTA slam
# mark ships on a plate of its own and keeps it (owner, 2026-09-15).
TAGS = ['250k-tag.png', '500k-tag.png', '1000k-tag.png']


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def ink_and_fill(px, w, h):
    """The two colours the art is made of: the lettering and the plate behind
    it. Read from the art rather than typed in — every one of these files is a
    flat fill under flat letters, and a hard-coded triple is a silent wrong
    answer the day the artwork is redrawn. The lettering is the lighter of the
    two in all of them (white or off-white on a colour)."""
    c = Counter(px[x, y] for y in range(0, h, 2) for x in range(0, w, 2))
    opaque = [col[:3] for col, _ in c.most_common(8) if col[3] == 255]
    if len(opaque) < 2:
        raise SystemExit('expected two flat colours — is this still a solid tag?')
    pair = sorted(opaque[:2], key=lum)
    return pair[1], pair[0]


for name in TAGS:
    src = Image.open(ART / name).convert('RGBA')
    w, h = src.size
    px = src.load()
    ink, bg = ink_and_fill(px, w, h)

    # Every pixel in the art sits on the line from the fill to the ink, because
    # the only shape in it is antialiased lettering. How far along that line a
    # pixel lies IS its coverage.
    span = [i - b for i, b in zip(ink, bg)]
    denom = sum(v * v for v in span) or 1

    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            t = sum(v * (c - o) for v, c, o in zip(span, (r, g, b), bg)) / denom
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            dst[x, y] = (*ink, round(a * t))

    target = ART / name.replace('.png', '-plate.png')
    out.save(target)
    covered = sum(1 for y in range(h) for x in range(w) if dst[x, y][3] > 8)
    print(f'{name}: {ink} lettering on {bg} -> transparent, '
          f'{covered} lettering px, wrote {target.name}')
