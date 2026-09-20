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

from PIL import Image, ImageChops, ImageStat

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


def _seen(art, bg):
    """What the eye gets: the art composited onto an opaque background.

    COMPARING RGBA DIRECTLY IS THE TRAP, and the first version of this tool
    fell in it. Where alpha is 0 the RGB is arbitrary — a quantizer writes
    black, the source had white — so a straight difference reported channels
    off by the full 255 in regions that cannot be seen at all, and the bound
    below was being set against noise. Composite first, then compare.
    """
    return Image.alpha_composite(Image.new('RGBA', art.size, bg), art).convert('RGB')


# The two grounds this art is ever drawn on: the app's card and the website's
# light theme. The worse of the two is the one that counts.
GROUNDS = ((13, 20, 17, 255), (255, 255, 255, 255))


def _error(a, b):
    """(rmse, worst channel) between two encodings AS DRAWN, in 0-255 units.

    AT THE SIZE A VIEWER SEES, not at 1:1. The art ships at 4x the box it is
    drawn in (see BOX), and no device made draws it larger than 3x, so the
    last step before the eye is a downscale to three quarters — which is part
    of what is being judged: it averages away the single-pixel disagreements
    a palette makes on an antialiased edge.

    Measured at 1:1 instead, every candidate here lands at rmse 2.9-3.5 and
    every one of them at 1.7-2.3 as drawn. The gap is the point: at 1:1 a
    bound has to be drawn through the middle of a cluster that all looks
    identical on a phone, and where it falls decides whether Roland Garros
    ships at 8.7 KB or 55.1 KB for the same picture.
    """
    b = b.convert('RGBA')
    size = (max(1, round(a.size[0] * 0.75)), max(1, round(a.size[1] * 0.75)))
    a, b = a.resize(size, Image.LANCZOS), b.resize(size, Image.LANCZOS)
    rmse = worst = 0
    for bg in GROUNDS:
        diff = ImageChops.difference(_seen(a, bg), _seen(b, bg))
        rmse = max(rmse, max(ImageStat.Stat(diff).rms))
        worst = max(worst, max(hi for _, hi in diff.getextrema()))
    return rmse, worst


def save_small(art, path, label=''):
    """Write `art` as the smallest PNG that is still the same picture.

    THE SIZE OF A PNG IS ITS ENCODING, not only its dimensions — which the
    first pass of this tool learned the hard way, shipping a 478x160 WTA mark
    of 344 colours as an 18 KB truecolour file where the 11.7 KB original had
    been bigger AND smaller. This artwork is flat: the ATP 250 stamp is
    seventeen colours, a crest a few hundred. A palette with alpha holds that
    exactly, in a quarter of the bytes.

    So: try truecolour and a 256 and 64-colour palette, and keep the
    smallest candidate whose error against the truecolour resize is under the
    bound. Nothing is accepted on faith, and the bound is not a round number
    someone liked — it sits in a gap that was measured. Squeezing the gold
    1000 stamp, the one real gradient here, until it visibly bands:

        p256   9.4 KB   rmse  2.32   worst  19     |  the whole nineteen-file
        p64    8.2 KB   rmse  3.12   worst  46     |  population lives here
        ----------------------------------------------- the bound, 3.0 / 64
        p16    6.5 KB   rmse  7.49   worst 200     |  banded
        p8     5.3 KB   rmse 14.97   worst 200     |
        p4     2.2 KB   rmse 30.17   worst 200     |

    Every acceptable candidate across all nineteen files falls in 1.7-3.1
    rmse and 15-46 worst; the first banded one is 7.5 and 200. The gap
    between 46 and 200 is where the worst-channel bound goes, and it is the
    band detector: banding is a hard edge where a smooth ramp was, so it
    shows up there an order of magnitude before rmse notices. rmse 3.0 then
    does the fine grading — it is what keeps the gold stamp on p256 rather
    than taking p64 and its extra kilobyte of saving.
    """
    best, best_size, best_note = art, None, 'rgba'
    from io import BytesIO
    for cand, note in [(art, 'rgba')] + [
            (art.quantize(colors=n, method=Image.FASTOCTREE), f'p{n}')
            for n in (256, 64)]:
        if note != 'rgba':
            rmse, worst = _error(art, cand)
            if rmse > 3.0 or worst > 64:
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
