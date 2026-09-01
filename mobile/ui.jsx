/* The handful of components every screen needs. Not a design system — just the
   pieces that would otherwise be copy-pasted four times and drift. */

import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { C, TOUCH } from './theme'

export function Screen({ children, scroll = true, edges = ['top', 'left', 'right'] }) {
  const Body = scroll ? ScrollView : View
  return (
    <SafeAreaView style={u.safe} edges={edges}>
      <Body {...(scroll ? { contentContainerStyle: u.body } : { style: u.body })}>
        {children}
      </Body>
    </SafeAreaView>
  )
}

export function Card({ children, style }) {
  return <View style={[u.card, style]}>{children}</View>
}

export function Title({ children, style }) {
  return <Text style={[u.title, style]}>{children}</Text>
}

export function Muted({ children, style }) {
  return <Text style={[u.muted, style]}>{children}</Text>
}

export function Row({ label, value }) {
  return (
    <View style={u.row}>
      <Text style={u.rowLabel}>{label}</Text>
      <Text style={u.rowValue}>{value}</Text>
    </View>
  )
}

export function Button({ label, onPress, busy, quiet }) {
  return (
    <Pressable
      style={({ pressed }) => [
        quiet ? u.btnQuiet : u.btn,
        pressed && { opacity: 0.7 },
      ]}
      onPress={onPress}
      disabled={busy}
      accessibilityRole="button"
    >
      {busy ? <ActivityIndicator color="#fff" />
            : <Text style={quiet ? u.btnQuietText : u.btnText}>{label}</Text>}
    </Pressable>
  )
}

export function Loading() {
  return (
    <View style={u.centre}>
      <ActivityIndicator color={C.accent} size="large" />
    </View>
  )
}

/* An error that says which KIND of failure it was. "Couldn't load" with no
   distinction between a dead network and a real server error is the thing that
   makes an app feel broken rather than offline. */
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
  body: { padding: 16, gap: 12, flexGrow: 1 },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 40 },
  card: {
    backgroundColor: C.card, borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: C.border, gap: 10,
  },
  title: { color: C.ink, fontWeight: '800', fontSize: 16 },
  muted: { color: C.muted, lineHeight: 20 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  rowLabel: { color: C.muted },
  rowValue: { color: C.ink, fontWeight: '600', flexShrink: 1, textAlign: 'right' },
  btn: {
    backgroundColor: C.green, borderRadius: 10, height: TOUCH,
    alignItems: 'center', justifyContent: 'center',
  },
  btnText: { color: '#fff', fontWeight: '800' },
  btnQuiet: {
    height: TOUCH, borderRadius: 10, borderWidth: 1, borderColor: C.border,
    alignItems: 'center', justifyContent: 'center',
  },
  btnQuietText: { color: C.muted, fontWeight: '700' },
})
