/*
 * The account's own controls — notification preferences, change password,
 * delete account — ported from the site's profile dropdown (Navbar.jsx),
 * copy and all.
 */
import { useEffect, useState } from 'react'
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { changePassword, deleteAccount, getNotificationPrefs, setNotificationPrefs } from './api'
import { useApi } from './useApi'
import { Sheet } from './sheet'
import { Button, Card, Muted, Title } from './ui'
import { C, S, T } from './theme'

/* The site's groups, labels and descriptions, verbatim. A row with
   `coveredBy` is implied by another — "Draw completion" is the last of the
   "Round completion" emails — and is locked on while its parent is. */
const GROUPS = [
  { title: 'General', rows: [
    { key: 'draw_released', label: 'New draw released', desc: 'Once a week, when all draws are out' },
    { key: 'league_member_joined', label: 'New league member', desc: 'Someone joins a league you own' },
  ]},
  { title: "Draws I'm competing in", rows: [
    { key: 'draw_changed', label: 'Draw change', desc: 'A player is replaced in a draw you entered' },
    { key: 'qualifiers_added', label: 'Qualifiers added', desc: 'Qualifying slots are filled, with their first matches' },
    { key: 'round_standings', label: 'Round completion', desc: 'After every round' },
    { key: 'tournament_end', label: 'Draw completion', desc: 'Final standings only', coveredBy: 'round_standings' },
  ]},
]

function Toggle({ on, locked, onPress, label }) {
  return (
    <Pressable onPress={locked ? undefined : onPress} hitSlop={6}
               accessibilityRole="switch" accessibilityState={{ checked: on, disabled: locked }}
               accessibilityLabel={label}
               style={[s.toggle, on && s.toggleOn, locked && { opacity: 0.45 }]}>
      <View style={[s.knob, on && s.knobOn]} />
    </Pressable>
  )
}

export function NotificationPrefs() {
  const q = useApi('notification-prefs', getNotificationPrefs)
  const [keys, setKeys] = useState(null)
  useEffect(() => { if (q.data?.enabled_keys && keys === null) setKeys(new Set(q.data.enabled_keys)) }, [q.data, keys])
  const has = k => !!keys?.has(k)

  const flip = k => {
    const next = new Set(keys)
    if (next.has(k)) next.delete(k); else next.add(k)
    setKeys(next)
    // Optimistic, like the site: the switch moves now, the save follows.
    setNotificationPrefs([...next]).catch(() => {})
  }

  return (
    <Card>
      <Title>Notifications</Title>
      {q.error ? <Muted>Couldn’t load your preferences.</Muted> : null}
      {keys ? GROUPS.map(g => (
        <View key={g.title} style={s.group}>
          <Text style={[T.eyebrow, { color: C.muted }]}>{g.title}</Text>
          <View style={s.headRow}>
            <View style={{ flex: 1 }} />
            <Text style={s.col}>Email</Text>
            <Text style={s.col}>Push</Text>
          </View>
          {g.rows.map(r => {
            const emailLocked = !!r.coveredBy && has(r.coveredBy)
            const pushLocked = !!r.coveredBy && has(`push_${r.coveredBy}`)
            return (
              <View key={r.key} style={s.row}>
                <View style={{ flex: 1 }}>
                  <Text style={[T.smallMed, { color: C.ink }]}>{r.label}</Text>
                  <Text style={[T.tiny, { color: C.faint }]}>
                    {emailLocked || pushLocked ? `Included in ${GROUPS.flatMap(x => x.rows).find(x => x.key === r.coveredBy)?.label}` : r.desc}
                  </Text>
                </View>
                <View style={s.colCell}><Toggle label={`${r.label} email`} on={emailLocked || has(r.key)} locked={emailLocked} onPress={() => flip(r.key)} /></View>
                <View style={s.colCell}><Toggle label={`${r.label} push`} on={pushLocked || has(`push_${r.key}`)} locked={pushLocked} onPress={() => flip(`push_${r.key}`)} /></View>
              </View>
            )
          })}
        </View>
      )) : null}
    </Card>
  )
}

export function PasswordSheet({ visible, onClose }) {
  const [cur, setCur] = useState(''); const [nw, setNw] = useState(''); const [cf, setCf] = useState('')
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [done, setDone] = useState(false)
  async function submit() {
    setError('')
    if (nw.length < 8) { setError('New password must be at least 8 characters'); return }
    if (nw !== cf) { setError('Passwords do not match'); return }
    setBusy(true)
    try { await changePassword(cur, nw); setDone(true); setCur(''); setNw(''); setCf('') }
    catch (e) { setError(e.offline ? 'Could not reach Upset Alert.' : (e.message || 'Could not change password')) }
    finally { setBusy(false) }
  }
  return (
    <Sheet visible={visible} onClose={onClose} title="Change password">
      <TextInput style={s.input} value={cur} onChangeText={setCur} placeholder="Current password" placeholderTextColor={C.muted}
                 secureTextEntry autoCapitalize="none" autoCorrect={false} textContentType="password" />
      <Text style={[T.eyebrow, { color: C.muted }]}>New password</Text>
      <TextInput style={s.input} value={nw} onChangeText={setNw} placeholder="New password (min 8 chars)" placeholderTextColor={C.muted}
                 secureTextEntry autoCapitalize="none" autoCorrect={false} textContentType="newPassword" />
      <Text style={[T.eyebrow, { color: C.muted }]}>Confirm new password</Text>
      <TextInput style={s.input} value={cf} onChangeText={setCf} placeholder="Confirm new password" placeholderTextColor={C.muted}
                 secureTextEntry autoCapitalize="none" autoCorrect={false} textContentType="newPassword" onSubmitEditing={submit} />
      {!!error && <Text style={{ color: C.bad }}>{error}</Text>}
      {done ? <Text style={{ color: C.greenLit }}>Password changed.</Text> : null}
      <Button label="Change password" onPress={submit} busy={busy} />
    </Sheet>
  )
}

export function DeleteAccountSheet({ visible, onClose, onDeleted }) {
  const [pw, setPw] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  async function submit() {
    if (!pw) return
    setBusy(true); setError('')
    try { await deleteAccount(pw); onDeleted?.() }
    catch (e) { setError(e.offline ? 'Could not reach Upset Alert.' : (e.message || 'Could not delete account')) }
    finally { setBusy(false) }
  }
  return (
    <Sheet visible={visible} onClose={onClose} title="Delete your account?">
      {/* The site's copy, verbatim. */}
      <Text style={[T.small, { color: C.inkBody }]}>
        This cannot be undone. Your email, name, password, passkeys and devices are permanently deleted.
      </Text>
      <TextInput style={s.input} value={pw} onChangeText={setPw} placeholder="Enter your password to confirm" placeholderTextColor={C.muted}
                 secureTextEntry autoCapitalize="none" autoCorrect={false} textContentType="password" onSubmitEditing={submit} />
      {!!error && <Text style={{ color: C.bad }}>{error}</Text>}
      <Pressable onPress={submit} disabled={!pw || busy} style={({ pressed }) => [s.danger, (!pw || busy) && { opacity: 0.5 }, pressed && { opacity: 0.7 }]}
                 accessibilityRole="button">
        <Text style={s.dangerText}>{busy ? 'Deleting…' : 'Delete my account'}</Text>
      </Pressable>
    </Sheet>
  )
}

const s = StyleSheet.create({
  group: { gap: 4, marginTop: 6 },
  headRow: { flexDirection: 'row', alignItems: 'center' },
  col: { ...T.tiny, color: C.faint, width: 52, textAlign: 'center' },
  colCell: { width: 52, alignItems: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.border },
  toggle: { width: 40, height: 24, borderRadius: 12, backgroundColor: C.control, borderWidth: 1, borderColor: C.borderOn, padding: 2, justifyContent: 'center' },
  toggleOn: { backgroundColor: C.green, borderColor: C.green },
  knob: { width: 18, height: 18, borderRadius: 9, backgroundColor: C.muted },
  knobOn: { backgroundColor: '#fff', alignSelf: 'flex-end' },
  input: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12, height: 44, fontSize: 16, color: C.ink },
  danger: { borderRadius: 999, backgroundColor: '#5a1f1c', borderWidth: 1, borderColor: C.bad, paddingVertical: 12, alignItems: 'center', marginTop: S.xs },
  dangerText: { ...T.bodyBold, color: C.bad },
})
