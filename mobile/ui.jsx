import { useState, useCallback } from 'react'
/* The shared pieces. Not a design system for its own sake — these are the
   components that would otherwise be copy-pasted into six screens and drift. */

import { ActivityIndicator, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useHeaderHeight } from '@react-navigation/elements'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Link } from 'expo-router'
import { C, R, S, T, TOUCH } from './theme'
import { leading } from './fontScale.js'

/* `edges` defaults to WHATEVER THE SCREEN ACTUALLY NEEDS.
 *
 * A screen with a native header must NOT also claim the top safe-area inset:
 * the header has already consumed it, so taking it again inserts a second
 * status bar's worth of empty space. That is what put a finger-deep band
 * between the "Schedule" title and the date — a gap so large it read as a
 * deliberately reserved slot rather than a bug.
 *
 * Detected rather than passed per screen, because three of the four tabs show
 * a header and remembering to opt out on each is exactly the kind of thing
 * that gets forgotten on the fourth. useHeaderHeight() is 0 when a screen sets
 * headerShown: false, so the dashboard still gets its inset.
 */
/* `touchAction` — web only, and only for a screen that hosts a SIDEWAYS
   gesture of its own (the schedule's swipe-to-change-day). The browser gives
   a touch to the nearest scroller whose touch-action allows it, and a
   ScrollView's is `auto`: two moves in, it claimed the drag as a native
   scroll and cancelled the pointer under the gesture (pointercancel), so the
   swipe fired only from a mouse. touch-action has to be ON THE ELEMENT THAT
   SCROLLS — the draw page learned the same on the site (memory
   reference-draw-swipe-paging) — so it goes on the ScrollView itself.
   `pan-y pinch-zoom`, never bare `pan-y`, which kills pinch. Native ignores
   it: gestures there never pass through the browser. */
export function Screen({
  children, scroll = true, edges, onRefresh, style, touchAction,
}) {
  const headerHeight = useHeaderHeight()
  const resolvedEdges = edges ?? (headerHeight > 0 ? ['left', 'right'] : ['top', 'left', 'right'])
  const Body = scroll ? ScrollView : View
  /* THE SPINNER IS THE USER'S PULL, NOTHING ELSE. Screens used to pass
     `refreshing={loading && !!data}` — true during every BACKGROUND refetch,
     and live scores refetch every few seconds. On iOS, flipping a
     RefreshControl to refreshing programmatically animates it into view
     and scrolls the list to the top, so the app looked as if it kept
     reloading itself and losing the reader's place. Now the control is
     refreshing only from a real pull until that pull's fetch settles;
     background refetches change the data in place and move nothing. */
  const [pulling, setPulling] = useState(false)
  const pull = useCallback(async () => {
    setPulling(true)
    try { await onRefresh?.() } finally { setPulling(false) }
  }, [onRefresh])
  const extra = scroll
    ? {
        contentContainerStyle: [u.body, style],
        style: Platform.OS === 'web' && touchAction ? { touchAction } : undefined,
        showsVerticalScrollIndicator: false,
        refreshControl: onRefresh ? (
          <RefreshControl
            refreshing={pulling} onRefresh={pull}
            tintColor={C.muted} colors={[C.clay]}
          />
        ) : undefined,
      }
    /* A body that does not scroll FILLS the safe area and no more: flex 1
       with a basis of 0 and shrink allowed. flexGrow alone let the web grow
       the body to its content (a percentage basis resolves to content there,
       where Yoga's resolves to zero), so a list inside it was as tall as the
       column, the viewport it reported was the whole column, and a pull
       anchored on that clamped to the top. */
    : { style: [u.body, u.bodyFill, style] }
  return (
    <SafeAreaView style={u.safe} edges={resolvedEdges}>
      <Body {...extra}>{children}</Body>
    </SafeAreaView>
  )
}

export function Card({ children, style, tint }) {
  return (
    <View style={[u.card, style]}>
      {tint ? <View style={[u.tint, { backgroundColor: tint }]} /> : null}
      {children}
    </View>
  )
}

/* THE BRAND MARK, STILL — a clay disc inside a dimmer ring.
 *
 * The same object as the wordmark's BrandDot on the dashboard, and the same
 * object as assets/icon.png: this app's logo is the dot, not the words. Drawn
 * as two Views rather than loaded from the PNG for three reasons — the PNG
 * bakes in its own dark background and would show as a square patch on a card,
 * it is 1024px for a 16pt mark, and Views take the reader's text scale.
 *
 * NO PULSE. BrandDot breathes because it sits beside the wordmark in the
 * header, where it is the app introducing itself. Here it is a STATE — which
 * draw you are looking at — and a state that throbs in a list is a list that
 * will not sit still.
 *
 * `size` is the disc-plus-ring diameter; the disc is half of it, which is
 * BrandDot's own ratio (30 and 15) and what the icon draws.
 */
export function BrandMark({ size = 16, style }) {
  return (
    <View style={[{
      width: size, height: size, borderRadius: size / 2,
      alignItems: 'center', justifyContent: 'center',
      /* The ring is the SAME ink at low alpha, not a second colour: that is
         how BrandDot builds it (it animates this between 0.15 and 0.42) and
         how the icon reads — a clay ring dimmed by the dark behind it. 0.3
         sits in the middle of that breath. */
      backgroundColor: C.clayLight + '4d',
    }, style]}>
      <View style={{
        width: size / 2, height: size / 2, borderRadius: size / 4,
        backgroundColor: C.clayLight,
      }} />
    </View>
  )
}

/* An all-caps label above a group. Condensed and letterspaced so it reads as a
   sign rather than as text someone forgot to sentence-case.
 *
 * 21pt, UP FROM T.eyebrow's 12 — that token times 1.75 (owner, 2026-09-16,
 * "increase the font size of the category names by 175%"). These are the signs
 * that divide the dashboard into Open / Active / Next week / Last week, and
 * the same component heads the schedule, the Hall of Fame and a league; at 12
 * they were smaller than the body text under them, which is backwards for
 * something whose whole job is to be found while scrolling past.
 *
 * THE SIZE LIVES HERE, NOT IN T.eyebrow, and that is deliberate: eleven other
 * places use that token for a FIELD label — "New password", "Invite code",
 * "Share via email" — where 21pt would be a heading standing over a text
 * input. This component is the section sign; the token is the small label.
 *
 * The line and the tracking scale with it, because a letterspacing tuned at
 * 12 reads as barely-tracked at 21.
 *
 * `small` IS THE SECOND SIZE, for a section that is CONTEXT rather than
 * something to act on — the dashboard's Next week and Last week against its
 * Open and Active (owner, 2026-09-16). 15 is 0.71 of 21, and that ratio is not
 * picked: it is the one the CARDS in those sections already use against the
 * cards above them, 13pt city and 11pt detail against 19 and 13 (0.68). So the
 * sign shrinks by about as much as the thing it labels, and the two pairs read
 * as two weights of one screen rather than four arbitrary sizes.
 *
 * Both sizes live here together because they are a pair, and a caller says
 * WHICH KIND of section it heads rather than a number. */
const EYEBROW = 21
const EYEBROW_SMALL = 15
/* The eyebrow's type, as a style and its tracking — for Eyebrow itself and
   for anything that must set the same eyebrow through a fitter (the
   schedule's court names, which may never wrap: FitText takes the style
   and the tracking separately, because tracking is measured per character). */
export function eyebrowType({ small = false, color = C.muted, size: sizeOverride } = {}) {
  const size = sizeOverride ?? (small ? EYEBROW_SMALL : EYEBROW)
  // Tracking in proportion, from the token's own 1.1 at 12.
  const track = 1.1 * (size / 12)
  return {
    track,
    style: [T.eyebrow, { fontSize: size, lineHeight: leading(size + 3), letterSpacing: track, color, textTransform: 'uppercase' }],
  }
}

export function Eyebrow({ children, color = C.muted, style, small = false }) {
  return <Text style={[eyebrowType({ small, color }).style, style]}>{children}</Text>
}

export function Title({ children, style }) {
  return <Text style={[T.h2, { color: C.ink }, style]}>{children}</Text>
}

export function Muted({ children, style, numberOfLines }) {
  return (
    <Text style={[T.small, { color: C.muted }, style]} numberOfLines={numberOfLines}>
      {children}
    </Text>
  )
}

export function Row({ label, value, valueColor = C.ink }) {
  return (
    <View style={u.row}>
      <Text style={[T.small, { color: C.muted }]}>{label}</Text>
      <Text style={[T.smallMed, { color: valueColor, flexShrink: 1, textAlign: 'right' }]}>
        {value}
      </Text>
    </View>
  )
}

/* A small status chip. `tone` picks the colour; the text is never the only
   signal, because colour alone fails for a good number of people. */
export function Pill({ children, tone = 'muted' }) {
  const fg = { open: C.clay, live: C.greenLit, muted: C.muted, bad: C.bad }[tone] || C.muted
  return (
    <View style={[u.pill, { borderColor: fg }]}>
      <Text style={[T.tiny, { color: fg, textTransform: 'uppercase', letterSpacing: 0.8 }]}>
        {children}
      </Text>
    </View>
  )
}

export function Button({ label, onPress, busy, quiet, tone = 'clay' }) {
  const bg = quiet ? 'transparent' : (tone === 'clay' ? C.clay : C.green)
  return (
    <Pressable
      style={({ pressed }) => [
        u.btn,
        { backgroundColor: bg, borderColor: quiet ? C.borderOn : bg },
        pressed && { opacity: 0.75 },
      ]}
      onPress={onPress} disabled={busy} accessibilityRole="button"
    >
      {busy ? <ActivityIndicator color={quiet ? C.muted : '#fff'} />
            : <Text style={[T.bodyBold, { color: quiet ? C.inkBody : '#fff' }]}>{label}</Text>}
    </Pressable>
  )
}

export function Loading() {
  return (
    <View style={u.centre}><ActivityIndicator color={C.clay} size="large" /></View>
  )
}

/* An error that says which KIND of failure it was. "Couldn't load" with no
   distinction between a dead network and a real server error is what makes an
   app feel broken rather than offline. */
export function ErrorNote({ error, onRetry }) {
  if (!error) return null
  const offline = error.offline
  return (
    <Card>
      <Title>{offline ? 'No connection' : 'Something went wrong'}</Title>
      <Muted>{offline ? 'Your phone could not reach Upset Alert.' : error.message}</Muted>
      {onRetry ? <Button label="Try again" onPress={onRetry} quiet /> : null}
    </Card>
  )
}

const u = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  body: { padding: S.lg, gap: S.md, flexGrow: 1, paddingBottom: S.xxl },
  bodyFill: { flex: 1, minHeight: 0 },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 40 },
  card: {
    backgroundColor: C.card, borderRadius: R.lg, padding: S.lg,
    borderWidth: 1, borderColor: C.border, gap: S.sm, overflow: 'hidden',
  },
  tint: { position: 'absolute', left: 0, top: 0, bottom: 0, width: 4 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: S.md, alignItems: 'baseline' },
  pill: {
    borderWidth: 1, borderRadius: R.pill,
    paddingHorizontal: S.sm, paddingVertical: 3, alignSelf: 'flex-start',
  },
  btn: {
    borderRadius: R.md, height: TOUCH, borderWidth: 1,
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: S.lg,
  },
})


/* A whole card that is also a link.
 *
 * THE VISUAL STYLE GOES ON AN INNER VIEW, never on the Pressable that
 * `Link asChild` clones. A card style placed on that Pressable is dropped: the
 * row loses its background, border and flex direction, collapsing to bare text
 * with the chevron stranded on its own line. Three screens had it wrong at once
 * — the leagues list, a league's draws, and the dashboard's compact rows — all
 * written the same plausible way, so the correct shape lives here instead of
 * being re-typed per screen.
 *
 * (Confirmed on the web renderer, which is what the visual-diff harness runs.
 * The inner-View form is what the dashboard's working cards already do, so it
 * is right on both targets either way.)
 */
export function CardLink({ href, style, children, pressedOpacity = 0.75, grow = false,
                           hitSlop, accessibilityLabel, pressedStyle }) {
  /* `grow`: take the row's spare width, so the whole row is the hit target and
     a sibling link after it lands at the edge.

     The flex lives on a View OUTSIDE the Link — not on the Pressable. A style
     on the Pressable that `Link asChild` clones is dropped (that is the whole
     reason this component exists), and a flex put there vanished the same way:
     the Last Week rows packed left with their icon floating mid-row. */
  /* hitSlop AND accessibilityLabel BELONG ON THE PRESSABLE, and they were not
     forwarded at all until now — callers had been passing accessibilityLabel
     to this component and having it silently dropped, which is the same class
     of bug as the dropped `style` this component exists to prevent. hitSlop is
     how a visually thin control still meets TOUCH: the strip is what you see,
     not what you have to hit (CompetingStar does the same). */
  /* `pressedStyle`, and `children` as a function of the press state: a caller
     whose pressed look is a COLOUR CHANGE rather than a fade needs both — the
     style to reach the inner View (the one that actually carries the caller's
     style, since a style on the Pressable is dropped by `Link asChild`), and
     the children to know, so a label can change with its plate.

     EITHER OF THEM REPLACES THE OPACITY FADE rather than stacking with it: a
     plate that lightens while the whole control dims is two answers to one
     press. Callers that pass neither are on exactly the path they were. */
  const dynamic = !!pressedStyle || typeof children === 'function'
  const inner = dynamic
    ? state => (
        <View style={[style, state.pressed && pressedStyle]}>
          {typeof children === 'function' ? children(state) : children}
        </View>
      )
    : <View style={style}>{children}</View>
  const link = (
    <Link href={href} asChild>
      <Pressable hitSlop={hitSlop} accessibilityLabel={accessibilityLabel}
                 style={({ pressed }) => (pressed && !dynamic
                   ? { opacity: pressedOpacity } : null)}>
        {inner}
      </Pressable>
    </Link>
  )
  return grow ? <View style={{ flex: 1 }}>{link}</View> : link
}

/* A HEADER'S RIGHT-HAND CONTROL WITHOUT THE GLASS (owner, 2026-09-23: the
   settings gear's "outer shell"). iOS 26 draws a Liquid Glass capsule around
   every item in the nav bar; hidesSharedBackground turns it off per item, and
   is reachable only through the item API (react-native-screens >= 4.17).
   headerRight stays alongside for Android and the web, which draw no capsule.
   Spread into a screen's options: `options={{ title, ...bareRight(() => …) }}`. */
export function bareRight(render) {
  if (!render) return {}
  return {
    headerRight: render,
    unstable_headerRightItems: () => [{ type: 'custom', element: render(), hidesSharedBackground: true }],
  }
}
