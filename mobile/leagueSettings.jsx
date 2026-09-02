/*
 * League settings, as a sheet — the site's LeagueSettings panel.
 *
 * Who sees it mirrors the server's _can_manage: the owner, a member the owner
 * made league admin, or a site admin. Everything here is the site's, field for
 * field: the name, "show real names", "members may invite", the members with
 * admin toggles and removal, and deletion behind a typed confirmation — a
 * league's whole history goes with it, so a tap is not enough.
 */
import { useState } from 'react'
import { useRouter } from 'expo-router'
import { Alert, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native'
import { deleteLeague, removeMember, setMemberAdmin, updateLeague } from './api'
import { Sheet } from './sheet'
import { C, R, S, T } from './theme'
import { Button } from './ui'
import { invalidate } from './useApi'

export function canManageLeague(league, me) {
  if (!league || !me) return false
  return league.owner?.id === me.id
    || (league.members ?? []).some(m => m.id === me.id && m.is_admin)
    || !!me.is_admin
}

/* window.confirm on the web build, Alert on the phone: one question, two
   answers, the site's own wording. */
function confirm(title, message) {
  if (Platform.OS === 'web') return Promise.resolve(globalThis.confirm ? globalThis.confirm(`${title}\n\n${message}`) : true)
  return new Promise(resolve => Alert.alert(title, message, [
    { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
    { text: 'Remove', style: 'destructive', onPress: () => resolve(true) },
  ]))
}

export function LeagueSettingsSheet({ visible, onClose, league }) {
  const router = useRouter()
  const [name, setName] = useState(league?.name ?? '')
  const [showReal, setShowReal] = useState(!!league?.show_real_name)
  const [allowInvites, setAllowInvites] = useState(!!league?.allow_member_invites)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [typed, setTyped] = useState('')

  if (!league) return null
  const refresh = () => { invalidate(`league:${league.id}`); invalidate('leagues') }
  const run = async (fn, after) => {
    setBusy(true); setError('')
    try { await fn(); refresh(); after?.() }
    catch (e) { setError(e?.message || 'Failed') }
    finally { setBusy(false) }
  }

  return (
    <Sheet visible={visible} onClose={onClose} title="League settings">
      {/* Nineteen members and a danger zone do not fit an 80% sheet. */}
      <ScrollView contentContainerStyle={{ gap: S.sm, paddingBottom: S.md }} keyboardShouldPersistTaps="handled">
      <Text style={s.label}>Name</Text>
      <TextInput value={name} onChangeText={setName} style={s.input} placeholderTextColor={C.faint}
                 autoCapitalize="words" returnKeyType="done" />
      <View style={s.switchRow}>
        <Text style={s.switchText}>Show members’ real names</Text>
        <Switch value={showReal} onValueChange={setShowReal} trackColor={{ true: C.green }} />
      </View>
      <View style={s.switchRow}>
        <Text style={s.switchText}>Allow all members to invite others</Text>
        <Switch value={allowInvites} onValueChange={setAllowInvites} trackColor={{ true: C.green }} />
      </View>
      {error ? <Text style={s.err}>{error}</Text> : null}
      <Button label="Save" busy={busy} tone="green"
              onPress={() => { if (!busy && name.trim()) run(() => updateLeague(league.id, {
                name: name.trim(), show_real_name: showReal, allow_member_invites: allowInvites,
              }), onClose) }} />

      <Text style={[s.label, { marginTop: S.md }]}>Members</Text>
      {(league.members ?? []).map(m => {
        const owner = m.id === league.owner?.id
        return (
          <View key={m.id} style={s.member}>
            <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <Text style={s.memberName} numberOfLines={1}>
                {league.show_real_name && m.full_name ? m.full_name : `@${m.username}`}
              </Text>
              {owner && <Text style={[s.badge, s.badgeOwner]}>Owner</Text>}
              {!owner && m.is_admin && <Text style={[s.badge, s.badgeAdmin]}>Admin</Text>}
            </View>
            {!owner && (
              <>
                <Pressable disabled={busy} hitSlop={6} style={[s.smallBtn, m.is_admin && s.smallBtnOn]}
                           onPress={() => run(() => setMemberAdmin(league.id, m.id, !m.is_admin))}
                           accessibilityLabel={m.is_admin ? 'Remove league admin' : 'Make league admin'}>
                  <Text style={[s.smallBtnText, m.is_admin && { color: '#fff' }]}>{m.is_admin ? 'Admin ✓' : 'Admin'}</Text>
                </Pressable>
                <Pressable disabled={busy} hitSlop={6} style={[s.smallBtn, s.smallBtnDanger]}
                           onPress={async () => {
                             if (await confirm(`Remove @${m.username}?`, 'They can rejoin with the invite code.')) {
                               run(() => removeMember(league.id, m.id))
                             }
                           }}>
                  <Text style={[s.smallBtnText, { color: C.lossMark }]}>Remove</Text>
                </Pressable>
              </>
            )}
          </View>
        )
      })}

      <View style={s.danger}>
        {!confirmDelete ? (
          <Pressable onPress={() => setConfirmDelete(true)} style={s.dangerBtn}>
            <Text style={s.dangerBtnText}>Delete league</Text>
          </Pressable>
        ) : (
          <>
            <Text style={s.warn}>
              This cannot be undone. Deleting this league permanently removes all members, history and leaderboard data.
            </Text>
            <Text style={s.switchText}>Type <Text style={{ fontFamily: 'Archivo_700Bold' }}>{league.name}</Text> to confirm:</Text>
            <TextInput value={typed} onChangeText={setTyped} style={s.input} placeholder={league.name}
                       placeholderTextColor={C.faint} autoCapitalize="none" autoCorrect={false} />
            <View style={{ flexDirection: 'row', gap: S.sm }}>
              <Pressable onPress={() => { setConfirmDelete(false); setTyped('') }} style={[s.smallBtn, { flex: 1, alignItems: 'center' }]}>
                <Text style={s.smallBtnText}>Cancel</Text>
              </Pressable>
              <Pressable disabled={busy || typed.trim() !== league.name}
                         onPress={() => run(() => deleteLeague(league.id), () => { onClose(); router.replace('/leagues') })}
                         style={[s.dangerBtn, { flex: 1 }, typed.trim() !== league.name && { opacity: 0.4 }]}>
                <Text style={s.dangerBtnText}>Delete league</Text>
              </Pressable>
            </View>
          </>
        )}
      </View>
      </ScrollView>
    </Sheet>
  )
}

const s = StyleSheet.create({
  label: { ...T.eyebrow, color: C.muted },
  input: {
    ...T.body, color: C.ink, backgroundColor: C.bg, borderWidth: 1, borderColor: C.border,
    borderRadius: R.md, paddingHorizontal: S.md, paddingVertical: S.sm,
  },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: S.md },
  switchText: { ...T.body, color: C.ink, flex: 1 },
  err: { ...T.small, color: C.lossMark },
  member: { flexDirection: 'row', alignItems: 'center', gap: S.sm, paddingVertical: 6, borderTopWidth: 1, borderColor: C.border },
  memberName: { ...T.bodyMed, color: C.ink, flexShrink: 1 },
  badge: { ...T.tiny, paddingHorizontal: 6, paddingVertical: 1, borderRadius: R.pill, overflow: 'hidden' },
  badgeOwner: { backgroundColor: C.clay, color: '#fff' },
  badgeAdmin: { backgroundColor: C.info, color: '#0b1a12' },
  smallBtn: { borderWidth: 1, borderColor: C.border, borderRadius: R.pill, paddingHorizontal: 10, paddingVertical: 4 },
  smallBtnOn: { backgroundColor: C.green, borderColor: C.green },
  smallBtnDanger: { borderColor: C.lossMark },
  smallBtnText: { ...T.tiny, color: C.ink },
  danger: { marginTop: S.md, gap: S.sm, borderTopWidth: 1, borderColor: C.border, paddingTop: S.md },
  dangerBtn: { borderWidth: 1, borderColor: C.lossMark, borderRadius: R.md, paddingVertical: S.sm, alignItems: 'center' },
  dangerBtnText: { ...T.smallMed, color: C.lossMark },
  warn: { ...T.small, color: C.warn },
})
