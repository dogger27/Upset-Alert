/* The shared pieces. Not a design system for its own sake — these are the
   components that would otherwise be copy-pasted into six screens and drift. */

import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Link } from 'expo-router'
import { C, R, S, T, TOUCH } from './theme'

export function Screen({
  children, scroll = true, edges = ['top', 'left', 'right'], onRefresh, refreshing, style,
}) {
  const Body = scroll ? ScrollView : View
  const extra = scroll
    ? {
        contentContainerStyle: [u.body, style],
        showsVerticalScrollIndicator: false,
        refreshControl: onRefresh ? (
          <RefreshControl
            refreshing={!!refreshing} onRefresh={onRefresh}
            tintColor={C.muted} colors={[C.clay]}
          />
        ) : undefined,
      }
    : { style: [u.body, style] }
  return (
    <SafeAreaView style={u.safe} edges={edges}>
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

/* An all-caps label above a group. Condensed and letterspaced so it reads as a
   sign rather than as text someone forgot to sentence-case. */
export function Eyebrow({ children, color = C.muted, style }) {
  return <Text style={[T.eyebrow, { color, textTransform: 'uppercase' }, style]}>{children}</Text>
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
export function CardLink({ href, style, children, pressedOpacity = 0.75 }) {
  return (
    <Link href={href} asChild>
      <Pressable style={({ pressed }) => (pressed ? { opacity: pressedOpacity } : null)}>
        <View style={style}>{children}</View>
      </Pressable>
    </Link>
  )
}
