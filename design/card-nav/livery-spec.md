# Card nav — "Livery" (chosen direction)

Redesign of `CardNav` in `mobile/cards.jsx`: the League / Draw / Schedule band at the bottom of Open, Active and Last-week cards on the Dashboard.

Reference mock: `Livery.html` (open in a browser; tap a word for the press state). Values below are the mock's, in points. Every color is an existing token from `mobile/theme.js` read through `useCardSkin()` — nothing new is introduced.

## Anatomy (left → right)

```
┌ band ───────────────────────────────────────────────────────┐
│ ▎▎▍▍  (speed lines)          ▱League ▱Draw ▱Schedule       │
└──────────────────────────────────────────────────────────────┘
       ← a 44pt gloss sweeps the whole band every 5.5 s →
```

**Band** — row, `alignItems:'center'`, `overflow:'hidden'` (needed for the sweep). Padding `8 / 14 / 10 / 16` (top/right/bottom/left). Top hairline `1pt` in `ornament` at 14% (`controlInk + '24'`). Sits on the card's own tint — no plate behind the band.

**Speed lines** — 4 Views, `height 26`, widths `2, 2, 3, 3`, gap `5`, `transform:[{skewX:'-20deg'}]`, background `ornament` at opacities `.10 .16 .24 .34` (rising toward the plates). A `flex:1` spacer after them pushes the plates right — the asymmetry survives any width.

**Plates** — row, gap `3`. Each plate: `height 26`, `paddingHorizontal 13`, `borderRadius 3`, background `skin.control` (the tier stamp's plate on a tinted card; `C.bg` on the neutral card), `transform:[{skewX:'-8deg'}]` — the same oblique as the ATP/WTA tier marks. The label is a child of the skewed View so it inherits the lean.

**Label** — `SairaCondensed_600SemiBold`, `13pt`, `lineHeight: leading(17)`, sentence case, **no letterSpacing**, color `skin.inkBody`. Deliberately quieter than today's 14pt `ink`.

**Gloss sweep** — one absolutely-positioned View: `width 44`, top→bottom of the band, `skewX -8deg`, horizontal gradient transparent → `ornament` 22% → transparent (do it as 5–7 side-by-side bands like `AccentBar`). `Animated.loop`: translateX from `-15%` to `105%` of the band width over `2.5 s` (ease-in-out), then hold hidden until `5.5 s`. Native driver. Stagger cards by index (e.g. `delay: index * 900`). Run it on **Open/Active only** — week cards stay still.

## States

- **Pressed** — plate background `mix(ornament 28%, control)` (≈ `ornament + '47'` over the plate), label → `skin.ink`. Hold ~150 ms.
- **Nothing to open** (`href` null) — plate stays (the band must not change shape card to card); label → `skin.faint`, plate at 55% opacity.
- **Quiet card** (`skin.quiet`, next/last week) — labels `skin.muted` instead of `inkBody`; no sweep.
- **Combined (neutral) card** — `control = C.bg`, `ornament = C.ink`; everything else identical.

## Touch

Plates are 26pt tall; add `hitSlop {top:9, bottom:9, left:2, right:2}` so each clears 44pt without the gap between plates letting one steal the other's center.

## Accessibility

Keep today's `accessibilityLabel`s (`League standings`, `Tournament draw`, `Schedule and order of play`) and the "— nothing published yet" suffix on dead items. Respect `AccessibilityInfo.isReduceMotionEnabled()` → skip the sweep.

## Contrast (checked on the mock)

`inkBody` on the WTA plate `#3a1526` ≈ 10:1, on the ATP plate `#14243d` ≈ 11:1; `faint` on either ≥ 6:1. Well over AA at 13pt.
