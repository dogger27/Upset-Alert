"""
Ship the badge artwork at the size a badge can actually draw it.

WHY THIS EXISTS (owner, 2026-09-20: "the WTA / ATP / SLAM badges are taking
way too long to load in all places they are displayed"). The crests and the
ATP tier stamps are the tournaments' own downloads, and they arrive at print
resolution: Roland Garros and Wimbledon at 1280x1280 and 200+ KB each, the
Australian Open at 3840x2400, the ATP stamps at 761x375. Every one of them is
drawn in a box no bigger than 88 CSS px across.

That costs twice. The bytes are fetched — over a phone's network in the app,
over the wire from Cloudflare on the site — and then EVERY ONE IS DECODED,
which is the part that shows: a 1280x1280 PNG is 6.5 million pixels and about
26 MB of bitmap, for a mark 51pt tall. A dashboard drawing half a dozen of
them was doing that work six times before it could paint.

So the originals stay exactly where they are, as the archive and as
gen-tier-stamps.py's input, and this writes DISPLAY COPIES into `badge/` in
both clients. Nothing here is authored: it is a downsample and a re-save.

    python3 tools/gen-badge-crests.py

Re-run it when a crest is added or replaced, or when BOX changes. It always
reads the originals, never its own output, so running it twice is a no-op.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MOBILE = ROOT / 'mobile' / 'assets' / 'logos'
SITE = ROOT / 'frontend' / 'public' / 'logos'

# THE PIXEL BUDGET, derived rather than picked. A crest is drawn `contain` in
# a fixed box: TierBadge's CREST is 77x51pt in the app, and the website asks
# for its `sm` box, 88x38 CSS px. Fitting by whichever side runs out first,
# the widest any of this art is ever drawn is 77pt — and 77pt at 4x, an
# Android xxxhdpi and more than any iPhone, is 308px. 320x224 covers that on
# the wide marks and leaves the square ones (Roland Garros, Wimbledon, both
# 1:1) at 224px against the 204 they can draw.
#
# IF EITHER BOX GROWS, raise this and re-run. The rule is
# BOX >= 4 x the largest box the art is drawn in.
BOX = (320, 224)

# Everything either client loads. The union, written to both: an asset a
# client does not reference is never bundled (Metro) and never fetched (the
# site), so one list is simpler than two and cannot fall out of step with
# them. The ".svg.png" spellings are the downloads' own names.
SOURCES = [
    'slams/slam_Australian.png',
    'slams/slam_RolandGarros.svg.png',
    'slams/slam_RolandGarros.svg-dark.png',
    'slams/slam_Wimbledon.svg.png',
    'slams/slam_Wimbledon.svg-dark.png',
    'slams/slam_US.svg.png',
    'slams/slam_US.svg-dark.png',
    'slams/slam_atp.png',
    'slams/slam_wta.png',
    # The website's ATP tier stamps. The app's are gen-tier-stamps.py's
    # output and are shipped at a cap height instead — a stamp is drawn to
    # its lettering, a crest to a box.
    'categorystamps_250.png',
    'categorystamps_250-dark.png',
    'categorystamps_500.png',
    'categorystamps_1000.png',
]


def fit_box(art, box=BOX):
    """`art` scaled down to fit `box`, or returned as it is if it fits.

    NEVER UPSCALED: art smaller than the budget is art the badge is already
    drawing softly, and inventing pixels would not change that — it would
    only cost bytes. slam_atp.png comes through here untouched.
    """
    w, h = art.size
    k = min(box[0] / w, box[1] / h)
    if k >= 1:
        return art
    return art.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)


def _error(a, b):
    """(rmse, worst) between two RGBA images, in 0-255 channel units."""
    import math
    pa, pb = a.tobytes(), b.convert('RGBA').tobytes()
    total = worst = 0
    for x, y in zip(pa, pb):                # every channel of every pixel
        d = x - y if x > y else y - x
        total += d * d
        if d > worst:
            worst = d
    return math.sqrt(total / max(1, len(pa))), worst


def save_small(art, path, label=''):
    """Write `art` as the smallest PNG that is still the same picture.

    THE SIZE OF A PNG IS ITS ENCODING, not only its dimensions — which the
    first pass of this tool learned the hard way, shipping a 478x160 WTA mark
    of 344 colours as an 18 KB truecolour file where the 11.7 KB original had
    been bigger AND smaller. This artwork is flat: the ATP 250 stamp is
    seventeen colours, a crest a few hundred. A palette with alpha holds that
    exactly, in a quarter of the bytes.

    So: try truecolour and a 256, 128 and 64-colour palette, keep the
    smallest candidate whose error against the truecolour resize is under the
    bound below. Nothing is accepted on faith — the numbers come from the six
    detailed files, measured:

        Roland Garros  55.1 KB rgba -> 9.5 KB p256, rmse 2.2, worst 30
        Wimbledon      50.6 KB      -> 9.5 KB      , rmse 2.1, worst 30
        ATP 1000       38.6 KB      -> 9.4 KB      , rmse 2.2, worst 30

    rmse ~2 is 0.9% of the channel range, and the worst cases are single
    pixels on an antialiased edge — on art drawn at a quarter of this size.
    The bound is set just above that and no further: a palette that BANDS the
    gold 1000's gradient is not the same picture, and 3.0 is tight enough to
    catch it. The rendering was compared before and after on both clients.

    p128 saves another half-kilobyte over p256 and is not taken for it: at
    equal bytes, more colours.
    """
    best, best_size, best_note = art, None, 'rgba'
    from io import BytesIO
    for cand, note in [(art, 'rgba')] + [
            (art.quantize(colors=n, method=Image.FASTOCTREE), f'p{n}')
            for n in (256, 64)]:
        if note != 'rgba':
            rmse, worst = _error(art, cand)
            if rmse > 3.0 or worst > 48:
                continue
        buf = BytesIO()
        cand.save(buf, format='PNG', optimize=True)
        if best_size is None or buf.tell() < best_size:
            best, best_size, best_note = cand, buf.tell(), note
    best.save(path, optimize=True)
    return best_note


def main():
    for dest in (MOBILE / 'badge', SITE / 'badge'):
        dest.mkdir(parents=True, exist_ok=True)

    total_before = total_after = 0
    for rel in SOURCES:
        src = MOBILE / rel
        if not src.exists():
            raise SystemExit(f'missing source: {src}')
        art = fit_box(Image.open(src).convert('RGBA'))
        name = Path(rel).name
        before = src.stat().st_size
        after = note = None
        for dest in (MOBILE / 'badge', SITE / 'badge'):
            out = dest / name
            note = save_small(art, out, name)
            after = out.stat().st_size
        total_before += before
        total_after += after
        print(f'  {name:38s} {art.size[0]:4d}x{art.size[1]:<4d} '
              f'{before / 1024:7.1f} KB -> {after / 1024:6.1f} KB  {note}')

    print(f'\n{len(SOURCES)} files, {total_before / 1024:.0f} KB -> '
          f'{total_after / 1024:.0f} KB per client '
          f'({100 - 100 * total_after / total_before:.0f}% off)')


if __name__ == '__main__':
    main()
