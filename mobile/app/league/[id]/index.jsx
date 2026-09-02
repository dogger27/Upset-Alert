/* The draws a league has played, newest first. Tap one for its standings. */

import { Stack, useLocalSearchParams } from 'expo-router'
import { useMemo, useState } from 'react'
import { Pressable, Share, StyleSheet, Text, TextInput, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { getLeague, getLeagueTournaments, shareLeagueByEmail } from '../../../api'
import { useAuth } from '../../../auth'
import { Sheet } from '../../../sheet'
import { useApi } from '../../../useApi'
import { TourBadge } from '../../../cards'
import { computeCohortInfo, getHomeSection } from '../../../drawStatus'
import { C, T } from '../../../theme'
import { Button, Card, CardLink, ErrorNote, Eyebrow, Loading, Muted, Screen, Title } from '../../../ui'

export default function LeagueDraws() {
  const { id } = useLocalSearchParams()
  const league = useApi(`league:${id}`, () => getLeague(id))
  const draws = useApi(`league:${id}:tournaments`, () => getLeagueTournaments(id))

  /* GROUPED THE WAY THE SITE GROUPS THEM. Every draw is filed by the same
     getHomeSection the dashboard uses — computed over ALL of this league's
     draws, because the cohort clustering moves the "last week" boundary if
     it is fed a subset — and then folded into two lists: what is open or
     running, and everything before. Previous is recency-first and shows
     five at a time, as on the site, so a league two seasons old does not
     open on a wall of history. */
  const { current, previous } = useMemo(() => {
    const ts = (draws.data || []).map(x => x.tournament).filter(Boolean)
    const cohort = computeCohortInfo(ts)
    const cur = [], prev = []
    for (const it of draws.data || []) {
      const t = it.tournament
      if (!t) continue
      const sec = getHomeSection(t, cohort)
      ;(sec === 'open' || sec === 'active' || sec === 'upcoming' ? cur : prev).push(it)
    }
    const byStart = (a, b) => (b.tournament?.start_date || '').localeCompare(a.tournament?.start_date || '')
    cur.sort(byStart); prev.sort(byStart)
    return { current: cur, previous: prev }
  }, [draws.data])
  const [prevShown, setPrevShown] = useState(5)
  const [invite, setInvite] = useState(false)
  const { me } = useAuth()

  return (
    <>
      <Stack.Screen options={{ title: league.data?.name || 'League' }} />
      <Screen onRefresh={draws.refetch} refreshing={draws.loading && !!draws.data}>
        {draws.loading && !draws.data ? <Loading /> : null}
        <ErrorNote error={draws.error} onRetry={draws.refetch} />

        {draws.data?.length === 0 && (
          <Card>
            <Title>No draws yet</Title>
            <Muted>This league hasn’t played a draw yet.</Muted>
          </Card>
        )}

        {/* The site's "Share League": the invite code, a way to send it, and
            share-by-email. Offered to the owner, or to any member when the
            league allows member invites — the site's own gate. */}
        {league.data?.invite_code && (league.data.owner?.id === me?.id || league.data.allow_member_invites) ? (
          <View style={s.invite}>
            <View style={{ flex: 1 }}>
              <Text style={[T.eyebrow, { color: C.muted }]}>Invite code</Text>
              <Text style={s.code}>{league.data.invite_code}</Text>
            </View>
            <Pressable onPress={() => setInvite(true)} style={({ pressed }) => [s.shareBtn, pressed && { opacity: 0.7 }]}>
              <Ionicons name="share-outline" size={16} color={C.greenLit} />
              <Text style={[T.smallMed, { color: C.greenLit }]}>Share</Text>
            </Pressable>
          </View>
        ) : null}
        <InviteSheet visible={invite} onClose={() => setInvite(false)} league={league.data} />

        {current.length > 0 && (
          <>
            <Eyebrow>Open / Active</Eyebrow>
            {current.map(it => (
              <DrawRow key={it.tournament.id} t={it.tournament}
                       pickers={it.picker_count} leagueId={id} />
            ))}
          </>
        )}
        {previous.length > 0 && (
          <>
            <Eyebrow>Previous ({previous.length})</Eyebrow>
            {previous.slice(0, prevShown).map(it => (
              <DrawRow key={it.tournament.id} t={it.tournament}
                       pickers={it.picker_count} leagueId={id} />
            ))}
            {prevShown < previous.length && (
              <Pressable onPress={() => setPrevShown(n => n + 5)} style={s.more} hitSlop={8}>
                <Text style={[T.smallMed, { color: C.greenLit }]}>
                  Show {Math.min(5, previous.length - prevShown)} more
                </Text>
              </Pressable>
            )}
          </>
        )}
      </Screen>
    </>
  )
}

function DrawRow({ t, pickers, leagueId }) {
  // Gender drives the accent because it is the fastest way to tell two halves
  // of the same combined event apart, which is exactly the case the web app's
  // combined cards exist for.
  // 'F', not 'W' — the API's genders are 'M' and 'F'. This tested 'W', which is
  // never true, so every stripe in the list rendered ATP blue including the WTA
  // draws. The TourBadge beside it keys on the same field correctly, which is
  // what made the disagreement visible at all.
  const tint = t.gender === 'F' ? C.wta : C.atp
  return (
    <CardLink href={`/league/${leagueId}/draw/${t.id}`} style={s.card}>
      <View style={[s.stripe, { backgroundColor: tint }]} />
      <View style={s.inner}>
        <View style={s.nameRow}>
          <Text style={s.name} numberOfLines={2}>{t.name}</Text>
          {/* Same reason as the dashboard: a combined event lists two draws
              under one name, and the accent stripe alone does not say which
              is which. */}
          <TourBadge gender={t.gender} />
        </View>
        <Text style={s.meta}>
          {[t.category, t.surface, t.year].filter(Boolean).join(' · ')}
        </Text>
        <Text style={s.meta}>
          {t.draw_size} draw · {pickers} {pickers === 1 ? 'picker' : 'pickers'}
        </Text>
      </View>
      <Text style={s.chev}>›</Text>
    </CardLink>
  )
}

const s = StyleSheet.create({
  card: {
    backgroundColor: C.card, borderRadius: 14, borderWidth: 1,
    borderColor: C.border, flexDirection: 'row', alignItems: 'center',
    overflow: 'hidden',
  },
  stripe: { width: 5, alignSelf: 'stretch' },
  inner: { flex: 1, padding: 14, gap: 3 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  name: { color: C.ink, fontWeight: '800', fontSize: 16, flexShrink: 1 },
  meta: { color: C.muted, fontSize: 13 },
  more: { alignSelf: 'center', paddingVertical: 8 },
  invite: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    backgroundColor: C.card, borderRadius: 14, borderWidth: 1, borderColor: C.border, padding: 12,
  },
  code: { fontFamily: 'SairaCondensed_700Bold', fontSize: 22, letterSpacing: 3, color: C.ink },
  codeBig: { fontFamily: 'SairaCondensed_700Bold', fontSize: 34, letterSpacing: 5, color: C.ink, textAlign: 'center', paddingVertical: 6 },
  shareBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: C.borderOn },
  input: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12, height: 44, fontSize: 16, color: C.ink },
  chev: { color: C.muted, fontSize: 22, paddingRight: 14 },
})


function InviteSheet({ visible, onClose, league }) {
  const [emails, setEmails] = useState('')
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState(null)
  const [error, setError] = useState('')
  const code = league?.invite_code || ''

  // The system share sheet, not the clipboard: a clipboard needs a native
  // module the build does not carry, and the share sheet reaches Messages,
  // Mail and the clipboard anyway.
  const share = () => Share.share({
    message: `Join my Upset Alert league "${league?.name}" with invite code ${code} — https://upsetalert.ca/leagues`,
  }).catch(() => {})

  async function sendEmails() {
    const list = emails.split(/[\s,;]+/).map(e => e.trim()).filter(Boolean)
    if (!list.length) return
    setBusy(true); setError(''); setResults(null)
    try { setResults(await shareLeagueByEmail(league.id, list)) }
    catch (e) { setError(e.offline ? 'Could not reach Upset Alert.' : (e.message || 'Could not send')) }
    finally { setBusy(false) }
  }

  return (
    <Sheet visible={visible} onClose={onClose} title="Share League">
      <Text style={[T.eyebrow, { color: C.muted }]}>Share via invite code</Text>
      <Text style={[T.small, { color: C.inkBody }]}>Anyone with this code can join from the Leagues tab.</Text>
      <Text style={s.codeBig} selectable>{code}</Text>
      <Button label="Share invite code" onPress={share} />

      <Text style={[T.eyebrow, { color: C.muted, marginTop: 8 }]}>Share via email</Text>
      <TextInput style={s.input} value={emails} onChangeText={setEmails} placeholder="one or more addresses"
                 placeholderTextColor={C.muted} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" />
      {(results || []).map((r, i) => (
        <Text key={i} style={[T.small, { color: r.status === 'added' ? C.greenLit : C.muted }]}>
          {r.status === 'added' ? `✓ ${r.email} — added as @${r.username}` : `${r.email} — ${r.status}`}
        </Text>
      ))}
      {!!error && <Text style={{ color: C.bad }}>{error}</Text>}
      <Button label="Send invites" quiet onPress={sendEmails} busy={busy} />
    </Sheet>
  )
}
