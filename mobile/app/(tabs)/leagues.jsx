/* The leagues you're in. Reached from the dashboard. */

import { Redirect } from 'expo-router'
import { useState } from 'react'
import { leading } from '../../fontScale.js'
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { useAuth } from '../../auth'
import { createLeague, getLeagues, joinLeague } from '../../api'
import { Sheet } from '../../sheet'
import { useApi } from '../../useApi'
import { C, T } from '../../theme'
import { Button, Card, CardLink, ErrorNote, Loading, Muted, Screen, Title } from '../../ui'

export default function Leagues() {
  const { phase, retry, error: authError } = useAuth()
  const ready = phase === 'ready'
  const [modal, setModal] = useState(null)
  const { data: leagues, error, loading, refetch } = useApi(
    ready ? 'leagues' : null, getLeagues, { enabled: ready },
  )

  if (phase === 'boot') return <Loading />
  if (phase === 'signedout') return <Redirect href="/sign-in" />

  if (phase === 'unreachable') {
    return (
      <Screen>
        <Card>
          <Title>Can’t reach Upset Alert</Title>
          <Muted>
            You’re still signed in — this is a connection problem, not a
            sign-out. Your session is untouched.
          </Muted>
          {!!authError && <Muted>{authError}</Muted>}
          <Button label="Retry" onPress={retry} />
        </Card>
      </Screen>
    )
  }

  return (
    <Screen onRefresh={refetch} refreshing={loading && !!leagues}>
      {loading && !leagues ? <Loading /> : null}
      <ErrorNote error={error} onRetry={refetch} />

      {/* Both of these are competition records rather than settings, so they
          belong beside the leagues and not on the Status tab. Two links rather
          than two more tabs: the bar stays at four. */}
      {/* The site's two buttons, its two forms. Create is private, classic
          scoring; Join takes the code the site prints in its invite modal. */}
      <View style={s.shortcuts}>
        <Pressable onPress={() => setModal('create')} style={({ pressed }) => [s.shortcut, pressed && { opacity: 0.7 }]}>
          <Text style={s.shortcutTitle}>Create a league</Text>
          <Text style={s.shortcutSub}>Private, invite by code</Text>
        </Pressable>
        <Pressable onPress={() => setModal('join')} style={({ pressed }) => [s.shortcut, pressed && { opacity: 0.7 }]}>
          <Text style={s.shortcutTitle}>Join a league</Text>
          <Text style={s.shortcutSub}>Enter an invite code</Text>
        </Pressable>
      </View>
      <LeagueForms modal={modal} onClose={() => setModal(null)} onChanged={refetch} />

      {leagues?.length === 0 && (
        <Card>
          <Title>No leagues yet</Title>
          <Muted>
            Join or create a league on the website and it will appear here.
          </Muted>
        </Card>
      )}

      {leagues?.map(l => <LeagueRow key={l.id} league={l} />)}

    </Screen>
  )
}

function LeagueRow({ league }) {
  return (
    <CardLink href={`/league/${league.id}`} style={s.card}>
      <View style={s.cardTop}>
        <Text style={s.name} numberOfLines={2}>{league.name}</Text>
        <Text style={s.chev}>›</Text>
      </View>
      <Text style={s.meta}>
        {league.member_count} {league.member_count === 1 ? 'member' : 'members'}
        {league.is_public ? ' · public' : ''}
      </Text>
    </CardLink>
  )
}

const s = StyleSheet.create({
  hello: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  who: { color: C.muted, fontWeight: '700' },
  shortcuts: { flexDirection: 'row', gap: 10 },
  shortcut: {
    flex: 1, backgroundColor: C.card, borderRadius: 14, borderWidth: 1,
    borderColor: C.border, padding: 12, gap: 2,
  },
  shortcutTitle: { color: C.ink, fontWeight: '800', fontSize: 14 },
  shortcutSub: { color: C.faint, fontSize: 11 },
  statusLink: { color: C.clay, fontWeight: '700', padding: 6 },
  card: {
    backgroundColor: C.card, borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: C.border, gap: 6,
  },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  name: { color: C.ink, fontWeight: '800', fontSize: 17, flex: 1 },
  chev: { color: C.muted, fontSize: 22, lineHeight: leading(22) },
  meta: { color: C.muted },
})


function LeagueForms({ modal, onClose, onChanged }) {
  const [name, setName] = useState('')
  const [showReal, setShowReal] = useState(false)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    setBusy(true); setError('')
    try {
      if (modal === 'create') await createLeague(name.trim(), showReal)
      else await joinLeague(code.trim().toUpperCase())
      setName(''); setCode(''); setShowReal(false)
      onChanged?.(); onClose()
    } catch (e) {
      setError(e.offline ? 'Could not reach Upset Alert.' : (e.message || 'Something went wrong'))
    } finally { setBusy(false) }
  }

  return (
    <Sheet visible={!!modal} onClose={onClose} title={modal === 'create' ? 'Create League' : 'Join a League'}>
      {modal === 'create' ? (
        <>
          <Text style={f.label}>Name</Text>
          <TextInput style={f.input} value={name} onChangeText={setName} placeholder="My Fantasy Group"
                     placeholderTextColor={C.muted} autoFocus autoCapitalize="words" returnKeyType="done" onSubmitEditing={submit} />
          <Pressable onPress={() => setShowReal(v => !v)} style={f.check} accessibilityRole="checkbox" accessibilityState={{ checked: showReal }}>
            <View style={[f.box, showReal && f.boxOn]}>{showReal ? <Text style={f.tick}>✓</Text> : null}</View>
            <Text style={[T.small, { color: C.inkBody }]}>Show real names</Text>
          </Pressable>
        </>
      ) : (
        <>
          <Text style={f.label}>Invite Code</Text>
          <TextInput style={[f.input, f.mono]} value={code} onChangeText={t => setCode(t.toUpperCase())}
                     placeholder="e.g. F5KP1" placeholderTextColor={C.muted} autoFocus autoCapitalize="characters"
                     autoCorrect={false} returnKeyType="go" onSubmitEditing={submit} />
        </>
      )}
      {!!error && <Text style={{ color: C.bad }}>{error}</Text>}
      <Button label={modal === 'create' ? 'Create League' : 'Join League'} onPress={submit} busy={busy} />
    </Sheet>
  )
}

const f = StyleSheet.create({
  label: { ...T.eyebrow, color: C.muted },
  input: {
    backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10,
    paddingHorizontal: 12, height: 44, fontSize: 16, color: C.ink,
  },
  mono: { fontFamily: 'SairaCondensed_600SemiBold', letterSpacing: 2, fontSize: 20 },
  check: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 4 },
  box: { width: 20, height: 20, borderRadius: 4, borderWidth: 1, borderColor: C.borderOn, alignItems: 'center', justifyContent: 'center' },
  boxOn: { backgroundColor: C.green, borderColor: C.green },
  tick: { color: '#fff', fontSize: 13, fontWeight: '800' },
})
