/* The draws a league has played, newest first. Tap one for its standings. */

import { Stack, useLocalSearchParams } from 'expo-router'
import { useEffect, useMemo, useState } from 'react'
import { Pressable, RefreshControl, Share, StyleSheet, Text, TextInput, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { getGlobalDraws, getGlobalGSTotals, getGrandSlamTotals, getLeague, getLeagueTournaments, shareLeagueByEmail } from '../../../../../api'
import { useAuth } from '../../../../../auth'
import { Sheet } from '../../../../../sheet'
import { LeagueSettingsSheet, canManageLeague } from '../../../../../leagueSettings'
import { LeaguePicker, LeagueTitle } from '../../../../../leaguePicker'
import { setLastLeague } from '../../../../../lastLeague'
import { useApi } from '../../../../../useApi'
import { PlayerName, TourBadge } from '../../../../../cards'
import { computeCohortInfo, getHomeSection } from '../../../../../drawStatus'
import { GROUP_TONE, groupDrawsByStatus, sectionOfMany, showGroupHeadings } from '../../../../../drawGroups'
import { C, R, S, T } from '../../../../../theme'
import { leading } from '../../../../../fontScale.js'
import { ScrollPane } from '../../../../../scrollPane'
import { Button, Card, CardLink, ErrorNote, Eyebrow, Loading, Muted, Screen, Title, bareRight, eyebrowType } from '../../../../../ui'

export default function LeagueDraws() {
  const { id } = useLocalSearchParams()
  /* GLOBAL IS A LEAGUE HERE, as it is on the site: the same screen, different
     sources. One component rather than two, because the moment they are two
     they drift — the site learned that once already
     (feedback_global_league_duplication). There is no /leagues/global on the
     server, so the league query is switched OFF rather than left to 404. */
  const isGlobal = String(id) === 'global'
  const league = useApi(isGlobal ? null : `league:${id}`, () => getLeague(id),
                        { enabled: !isGlobal })
  const scope = isGlobal ? 'global' : `league:${id}`
  const draws = useApi(`${scope}:tournaments`,
                       () => (isGlobal ? getGlobalDraws() : getLeagueTournaments(id)))

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
      /* A DRAW ONE MEMBER PICKED IS NOT A COMPETITION. picker_count is
         already scoped to this league's members, so one means the reader was
         alone in it and there is nothing to have finished ahead of or behind.
         The site has hidden these from a real league's lists all along; the
         app never got the rule, which is why a phone listed draws only the
         reader had entered (owner, 2026-09-11). This page is only ever a real
         league. GLOBAL IS THE EXCEPTION — alone in a draw is still a result
         when the field is everybody — and it is this same screen now, so the
         rule is conditional rather than absolute. */
      if (!isGlobal && (it.picker_count ?? 0) <= 1) continue
      const sec = getHomeSection(t, cohort)
      ;(sec === 'open' || sec === 'active' || sec === 'upcoming' ? cur : prev).push(it)
    }
    const byStart = (a, b) => (b.tournament?.start_date || '').localeCompare(a.tournament?.start_date || '')
    cur.sort(byStart); prev.sort(byStart)
    /* ONE CARD PER EVENT, as the site does it: the two draws of a combined
       tournament are its men's and women's halves, not two tournaments —
       grouped on their shared tournament_id, or on name and year where the
       API has none. Men first, so a pair always opens on the same side and
       the badges never swap order between events. */
    const events = list => {
      const out = [], by = new Map()
      for (const it of list) {
        const t = it.tournament
        const key = t.tournament_id ?? `${t.name}|${t.year}`
        if (!by.has(key)) { const g = { key, items: [] }; by.set(key, g); out.push(g) }
        by.get(key).items.push(it)
      }
      for (const g of out) {
        g.items.sort((x, y) => (x.tournament.gender === 'M' ? 0 : 1) - (y.tournament.gender === 'M' ? 0 : 1))
        /* WHICH HEADING THIS CARD SITS UNDER (owner, 2026-09-19). Worked out
           here because `cohort` is in scope — it is clustered over every draw
           in the league, and recomputing it from a filtered list moves the
           boundaries (choosableTournaments.js). A combined card takes the more
           open of its two halves; sectionOfMany has the reasoning. */
        g.section = sectionOfMany(g.items.map(x => getHomeSection(x.tournament, cohort)))
      }
      return out
    }
    return { current: events(cur), previous: events(prev) }
  }, [draws.data, isGlobal])
  /* The Open / Active tab's cards in their status groups. Cheap — a filter
     over the handful of events a league is playing — so no memo. */
  const currentGroups = groupDrawsByStatus(current, g => g.section)
  const currentHeadings = showGroupHeadings(currentGroups)
  /* WHAT EACH TAB IS LISTING, one draw per event in its order, handed to the
     standings so their next-draw button walks this list (owner, 2026-09-23). */
  const currentCycle = currentGroups.flatMap(grp => grp.draws.map(g => g.items[0].tournament.id)).join(',')
  const [prevShown, setPrevShown] = useState(5)
  /* SHOW ONLY THE EVENTS THIS LEAGUE PLAYED FOR MONEY — the site's Previous
     filter. Most useful here, where a season's draws pile up and the question
     becomes "how did I do in the ones that counted". */
  const [poolOnly, setPoolOnly] = useState(false)
  /* An event is a cash event when EITHER half ran a pool: a combined card is
     one row and hiding it would hide the half that did. */
  const isPooled = g => g.items.some(x => x.cash_pool_enabled)
  const prevPooled = previous.some(isPooled)
  const prevList = poolOnly ? previous.filter(isPooled) : previous
  // What Previous is SHOWING — the cash-pool filter and "Show more" included.
  const prevCycle = prevList.slice(0, prevShown).map(g => g.items[0].tournament.id).join(',')
  const [invite, setInvite] = useState(false)
  const [picking, setPicking] = useState(false)
  /* WHICH LEAGUE THE TAB REOPENS. Reported from the screen that is showing it,
     exactly as the draw screen reports its draw — so the tab follows the
     reader rather than a guess. */
  useEffect(() => { if (id != null) setLastLeague(id) }, [id])
  const [settings, setSettings] = useState(false)
  /* ONE SECTION AT A TIME. The page was three lists end to end — the draws
     being played, the ones finished, and the member tally — so reaching the
     tally meant scrolling past a season (owner, 2026-09-14).

     The switch offers only sections that EXIST: a league with nothing
     finished has no Previous to select, and a tab over an empty list reads as
     broken. Members is always there, so there is always something to show.

     `tabRaw` is validated against that list rather than trusted, which is what
     makes the empty case safe: a league whose last open draw finishes while
     the page is up falls back to the first section still standing instead of
     rendering nothing. */
  const [tabRaw, setTab] = useState(null)
  const tabs = [
    current.length > 0 && { key: 'current', label: 'Open / Active' },
    previous.length > 0 && { key: 'previous', label: 'Previous' },
    { key: 'members', label: isGlobal ? 'Players' : 'Members' },
  ].filter(Boolean)
  const tab = tabs.some(x => x.key === tabRaw) ? tabRaw : tabs[0].key
  /* The site's Members tab: this year's Grand Slam point tally, ATP / WTA /
     combined, sortable by any column. Combined, descending, to start — the
     column the site opens on. */
  const gs = useApi(`${scope}:gs`, () => (isGlobal ? getGlobalGSTotals() : getGrandSlamTotals(id)))
  const [sortCol, setSortCol] = useState('combined')
  const [sortDir, setSortDir] = useState('desc')
  const members = useMemo(() => {
    const raw = gs.data?.members ?? (league.data?.members ?? []).map(m => ({
      user_id: m.id, username: m.username, full_name: m.full_name, is_admin: m.is_admin,
      atp_points: null, wta_points: null,
    }))
    const rows = raw.map(m => ({
      ...m,
      combined_points: m.atp_points != null && m.wta_points != null ? m.atp_points + m.wta_points : null,
    }))
    const key = { atp: 'atp_points', wta: 'wta_points', combined: 'combined_points' }[sortCol]
    return [...rows].sort((a, b) => {
      const av = a[key] ?? -Infinity, bv = b[key] ?? -Infinity
      return sortDir === 'desc' ? bv - av : av - bv
    })
  }, [gs.data, league.data, sortCol, sortDir])
  const sortBy = col => {
    if (sortCol === col) setSortDir(d => (d === 'desc' ? 'asc' : 'desc'))
    else { setSortCol(col); setSortDir('desc') }
  }
  const { me } = useAuth()

  return (
    <>
      {/* THE NAME IS THE CONTROL. The Leagues tab opens the league last
          read rather than a list (lastLeague), so changing league happens
          here — a larger name with a chevron, the same gesture as the draw
          chooser on the tab bar. headerTitle rather than `title`, because a
          string cannot be pressed. */}
      <Stack.Screen options={{
        headerTitle: () => (
          <LeagueTitle name={isGlobal ? 'Global' : league.data?.name} onPress={() => setPicking(true)} />
        ),
        /* THE GEAR BELONGS IN THE BAR, level with the name by construction
           rather than by arithmetic. It sat in the page under the title,
           sharing a line with the section switch — where it took width from
           the control used on every visit and pushed it off centre (owner,
           2026-09-14). The bar's right slot is where a screen's one
           configuration door goes.

           Icon only, 28pt, and bare: bareRight turns off the Liquid Glass
           capsule iOS 26 draws round a bar item (owner, 2026-09-23). The
           accessibility label carries the word "Settings". */
        ...bareRight(!isGlobal && canManageLeague(league.data, me)
          ? () => (
            <Pressable onPress={() => setSettings(true)} hitSlop={10}
                       style={({ pressed }) => [s.gear, pressed && { opacity: 0.6 }]}
                       accessibilityRole="button" accessibilityLabel="League settings">
              <Ionicons name="settings-outline" size={28} color={C.ink} />
            </Pressable>
          )
          : null),
      }} />
      <LeaguePicker visible={picking} onClose={() => setPicking(false)} currentId={id} />
      <Screen onRefresh={tab === 'members' ? undefined : draws.refetch} scroll={tab !== 'members'}
              style={tab === 'members' ? { paddingBottom: 0 } : undefined}>
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
        {!isGlobal && league.data?.invite_code && (league.data.owner?.id === me?.id || league.data.allow_member_invites) ? (
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
        {/* The site's gear: owner, league admin or site admin — the server's
            _can_manage, mirrored so the sheet never opens on a 403. */}
        {/* THE SWITCH, CENTRED, SIZED TO ITS LABELS. With the gear gone to
            the bar it no longer has to share a line, so the segments can take
            the width their words need instead of an equal third — three
            stretched thirds put "Previous" adrift in its box while
            "Open / Active" was still shrinking to fit in the one beside it.
            Now nothing shrinks and the group centres under the title. */}
        {/* MEMBERS IS ITS OWN CONTROL (owner, 2026-09-23). Open / Active and
            Previous are two views of the same thing — this league's draws —
            so they share one switch; the member tally is a different subject
            and sits beside it as a separate pill. Labels shrink to fit rather
            than end in "…". */}
        {tabs.length > 1 && (
          <View style={s.tabBar}>
            {[tabs.filter(x => x.key !== 'members'), tabs.filter(x => x.key === 'members')]
              .filter(group => group.length).map((group, gi) => (
              <View key={gi} style={[s.tabs, s.tabGroup]}>
                {group.map(x => (
                  <Pressable key={x.key} onPress={() => setTab(x.key)}
                             style={({ pressed }) => [s.tab, tab === x.key && s.tabOn, pressed && { opacity: 0.7 }]}
                             accessibilityRole="button" accessibilityState={{ selected: tab === x.key }}>
                    <Text style={[s.tabText, tab === x.key && s.tabTextOn]}
                          numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>
                      {x.label}
                    </Text>
                  </Pressable>
                ))}
              </View>
            ))}
          </View>
        )}
        {settings ? (
          <LeagueSettingsSheet key={league.data?.id} visible={settings} onClose={() => setSettings(false)} league={league.data} />
        ) : null}

        {/* GROUPED BY STATUS (owner, 2026-09-19), the same three headings the
            dashboard and the tab bar's draw chooser use — the tab holds draws
            still taking picks, draws being played and next week's releases,
            and flat it read as one list of all three. One group draws no
            heading: see drawGroups.showGroupHeadings. */}
        {tab === 'current' && currentGroups.map(grp => (
          <View key={grp.key} style={s.statusGroup}>
            {currentHeadings ? (
              <View style={s.statusHead}>
                <Eyebrow color={C[GROUP_TONE[grp.key]] || C.muted}>{grp.title}</Eyebrow>
                <View style={s.statusRule} />
              </View>
            ) : null}
            {grp.draws.map(g => (
              <DrawRow key={g.key} items={g.items} leagueId={id} isGlobal={isGlobal} cycle={currentCycle} />
            ))}
          </View>
        ))}
        {tab === 'previous' && (
          <>
            {/* The count and the filter share a line: a chip of its own would
                cost a row of a list that is meant to be scanned. */}
            <View style={s.prevHead}>
              <Eyebrow>Previous ({prevList.length})</Eyebrow>
              {prevPooled ? (
                <Pressable onPress={() => { setPoolOnly(v => !v); setPrevShown(5) }} hitSlop={6}
                           accessibilityRole="button" accessibilityState={{ selected: poolOnly }}
                           style={({ pressed }) => [s.poolChip, poolOnly && s.poolChipOn, pressed && { opacity: 0.7 }]}>
                  <Text style={[s.poolChipText, poolOnly && s.poolChipTextOn]}>💰 Cash pool</Text>
                </Pressable>
              ) : null}
            </View>
            {prevList.slice(0, prevShown).map(g => (
              <DrawRow key={g.key} items={g.items} leagueId={id} isGlobal={isGlobal} compact cycle={prevCycle} />
            ))}
            {prevShown < prevList.length && (
              <Pressable onPress={() => setPrevShown(n => n + 5)} style={s.more} hitSlop={8}>
                <Text style={[T.smallMed, { color: C.greenLit }]}>
                  Show {Math.min(5, prevList.length - prevShown)} more
                </Text>
              </Pressable>
            )}
          </>
        )}

        {/* THE MEMBERS TABLE IS THE STANDINGS TABLE (owner, 2026-09-23: "use
            all the same page formatting as the standings page"): no card,
            rows edge to edge, the header row pinned with its green rule, the
            sorted column lit green in the header and inked in the rows, the
            same type, and the same always-visible scroll bar. The tab trades
            the page's scroll for the table's own, which is what lets the
            header stay put. */}
        {tab === 'members' && (league.data || isGlobal) && (
          <>
            {/* The table's title, and only that — no member count (owner,
                2026-09-23) — on ONE line: it shrinks before it wraps. */}
            <Text style={eyebrowType().style} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>
              {`${gs.data?.year ?? new Date().getFullYear()} Grand Slam points`}
            </Text>
            <ScrollPane overlay style={s.mScroller} contentContainerStyle={{ paddingBottom: 4 }}
                        stickyHeaderIndices={[0]}
                        refreshControl={<RefreshControl refreshing={false} onRefresh={gs.refetch}
                                                        tintColor={C.muted} colors={[C.clay]} />}>
              {/* A plain View first: iOS replaces a sticky child's style
                  (feedback_rn_sticky_header_style_stripped). */}
              <View>
                <View style={[s.mRow, s.mHead]}>
                  <Text style={[s.mHeadText, s.mWho]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>
                    {isGlobal ? 'Player' : 'Member'}
                  </Text>
                  {[['atp', 'ATP'], ['wta', 'WTA'], ['combined', 'Total']].map(([col, label]) => (
                    <Pressable key={col} onPress={() => sortBy(col)} hitSlop={8}
                               accessibilityRole="button" accessibilityLabel={`Sort by ${label}`}
                               accessibilityState={{ selected: sortCol === col }}>
                      <Text style={[s.mHeadText, s.mNum, sortCol === col && s.mHeadOn]}
                            numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>{label}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
              <View style={s.mRows}>
                {members.map((m, i) => {
                  const mine = me && m.user_id === me.id
                  return (
                    <View key={m.user_id} style={[i % 2 ? s.mAlt : null, mine && s.mMine]}>
                      {/* The row is the door to their draw history, as the
                          site's person icon is. */}
                      <CardLink href={{ pathname: '/history', params: { user: m.user_id } }} grow style={s.mRow}>
                        <View style={s.mWho}>
                          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                            <View style={{ flex: 1, minWidth: 0 }}>
                              <PlayerName name={m.username} shrinkOnly style={[s.mName, mine && s.mNameMine]} />
                            </View>
                            {m.is_admin ? <Text style={s.adminBadge}>A</Text> : null}
                          </View>
                          {/* A league decides whether to show real names;
                              Global has no such setting and shows none. */}
                          {league.data?.show_real_name && m.full_name ? (
                            <PlayerName name={m.full_name} style={s.mReal} />
                          ) : null}
                        </View>
                        {[['atp', m.atp_points], ['wta', m.wta_points], ['combined', m.combined_points]].map(([col, v]) => (
                          <Text key={col} style={[s.mNumText, s.mNum, sortCol === col && s.mOn]}
                                numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>{v ?? '–'}</Text>
                        ))}
                      </CardLink>
                    </View>
                  )
                })}
              </View>
            </ScrollPane>
          </>
        )}
      </Screen>
    </>
  )
}

/* The tier WITHOUT its tour, for a card that covers both: the men's draw
   is "ATP 1000" and the women's "WTA 1000", and the shared fact is 1000.
   The site's own rule, verbatim. */
function tierLabel(category) {
  const c = (category || '').toUpperCase()
  if (c.includes('SLAM') || c.includes('GRAND')) return 'Grand Slam'
  if (c.includes('1000')) return '1000'
  if (c.includes('500')) return '500'
  return '250'
}

function DrawRow({ items, leagueId, isGlobal = false, compact = false, cycle = '' }) {
  /* Global's standings for a draw are their own screen — /standings/[id],
     everyone who entered — where a league's are scoped to its members. */
  const href = drawId => (isGlobal ? `/standings/${drawId}`
    : { pathname: `/league/${leagueId}/draw/${drawId}`, params: cycle ? { cycle } : {} })
  const a = items[0].tournament
  const b = items[1]?.tournament
  const paired = !!b
  /* Gender drives the accent because it is the fastest way to tell two halves
     of the same combined event apart. A COMBINED card is both halves at once,
     so its stripe is too — blue over pink, in the badges' own order.
     'F', not 'W' — the API's genders are 'M' and 'F'. This tested 'W', which
     is never true, so every stripe in the list rendered ATP blue including
     the WTA draws. */
  const tint = a.gender === 'F' ? C.wta : C.atp
  /* THE TWO HALVES ARE NOT ALWAYS THE SAME TIER. Twenty 2026 events pair
     draws whose categories differ, and eight differ in the NUMBER, not just
     the tour: Stuttgart is WTA 500 beside ATP 250, Dubai WTA 1000 beside ATP
     500. One tier taken from the men's draw would have mislabelled the
     women's half — and they score differently, since the points table keys
     off each draw's own category. So: the shared tier when they agree, both
     categories when they do not, men first, each naming its tour. */
  const tiers = paired ? [tierLabel(a.category), tierLabel(b.category)] : null
  const tierText = !paired ? a.category
    : tiers[0] === tiers[1] ? tiers[0]
      : items.map(x => x.tournament.category).filter(Boolean).join(' · ')
  /* NO SIZE OR PICKER COUNT on the card (owner, 2026-09-23: "remove the
     '5 entered, 32 draw' from all leagues and draws"). */
  const pooled = items.some(x => x.cash_pool_enabled)
  /* A FINISHED DRAW ASKS A SMALLER QUESTION. Open and active want the tier,
     the surface, the size and who is in — a card you read. Previous is a
     season's history being scanned, so it keeps the name, the tours, the
     money and the one line that separates two editions of the same event:
     which tier it was and when. Surface and draw size go; they are the same
     every year and nobody scans a history for them. */
  if (compact) {
    return (
      <CardLink href={href(a.id)} style={s.card}>
        {paired ? (
          <View style={s.stripe}>
            <View style={[s.stripeHalf, { backgroundColor: C.atp }]} />
            <View style={[s.stripeHalf, { backgroundColor: C.wta }]} />
          </View>
        ) : (
          <View style={[s.stripe, { backgroundColor: tint }]} />
        )}
        <View style={[s.inner, s.innerCompact]}>
          <View style={s.nameRow}>
            <Text style={[s.name, s.nameCompact]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>{a.name}</Text>
            {pooled ? <Text style={s.bag} accessibilityLabel="Cash pool">💰</Text> : null}
          </View>
          <Text style={s.meta} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}>
            {[tierText, a.year].filter(Boolean).join(' · ')}
          </Text>
        </View>
        <Tours a={a} paired={paired} />
      </CardLink>
    )
  }
  return (
    <CardLink href={href(a.id)} style={s.card}>
      {paired ? (
        <View style={s.stripe}>
          <View style={[s.stripeHalf, { backgroundColor: C.atp }]} />
          <View style={[s.stripeHalf, { backgroundColor: C.wta }]} />
        </View>
      ) : (
        <View style={[s.stripe, { backgroundColor: tint }]} />
      )}
      <View style={s.inner}>
        <View style={s.nameRow}>
          <Text style={s.name} numberOfLines={2} adjustsFontSizeToFit minimumFontScale={0.5}>{a.name}</Text>
          {pooled ? <Text style={s.bag} accessibilityLabel="Cash pool">💰</Text> : null}
        </View>
        <Text style={s.meta}>
          {[tierText, a.surface, a.year].filter(Boolean).join(' · ')}
        </Text>
      </View>
      <Tours a={a} paired={paired} />
    </CardLink>
  )
}

/* THE TOURS, AT THE CARD'S RIGHT EDGE.
 *
 * They used to trail the name inside a wrapping row, so the pill landed at a
 * different x on every card and, on a long name, dropped to a second line —
 * and the chevron held the right edge instead. The chevron said only "this
 * opens", which every card in the list does and the whole list already
 * implies; the tours say WHICH draws are behind it. The one carrying
 * information gets the fixed column (owner, 2026-09-14).
 *
 * Both halves named on a combined card: the split stripe alone does not say
 * the event has two draws you can open.
 */
function Tours({ a, paired }) {
  return (
    <View style={s.tours}>
      {paired
        ? <><TourBadge gender="M" /><TourBadge gender="F" /></>
        : <TourBadge gender={a.gender} />}
    </View>
  )
}

const s = StyleSheet.create({
  stripeHalf: { flex: 1 },
  gear: { paddingHorizontal: 4, paddingVertical: 4 },
  /* A capsule of capsules: the shell rounded as far as it goes and the live
     segment rounded to match, so the selection reads as a token lifted out of
     the track rather than a rectangle laid over it. The hairline is what
     separates the shell from the page — raised-on-sunken alone is two greys
     a point apart and, on a phone in daylight, no edge at all. */
  tabBar: { flexDirection: 'row', justifyContent: 'center', gap: 8 },
  // Each group shrinks before it overflows the row, and its labels with it.
  tabGroup: { flexShrink: 1 },
  tabs: {
    alignSelf: 'center', flexDirection: 'row', gap: 2,
    backgroundColor: C.sunken, borderRadius: R.pill, padding: 3,
    borderWidth: 1, borderColor: C.border,
  },
  tab: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: R.pill, flexShrink: 1 },
  tabOn: { backgroundColor: C.raised, borderWidth: 1, borderColor: C.borderOn },
  /* No lineHeight: on iOS the extra leading lands above the glyphs and pushes
     the caps off a short strip's centre. The row centres the text.
     The live label goes BOLD as well as bright — weight survives a glance
     that colour alone does not. */
  tabText: { fontFamily: 'Archivo_500Medium', fontSize: 13, color: C.muted },
  tabTextOn: { fontFamily: 'Archivo_700Bold', color: C.ink },
  /* Previous: one line of name, one of meta, and less air than a card being
     read rather than scanned. The height comes from the INNER padding, not
     the card's — trimming the card did nothing at all. */
  innerCompact: { paddingVertical: 8 },
  nameCompact: { fontSize: 15 },
  bag: { fontSize: 13 },
  /* A status group and its heading — the dashboard's Section head, the same
     three numbers, so the league page and the home screen read alike. */
  statusGroup: { gap: 10 },
  statusHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statusRule: { flex: 1, height: 1, backgroundColor: C.border },
  prevHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  poolChip: {
    paddingHorizontal: 10, paddingVertical: 3, borderRadius: R.pill,
    borderWidth: 1, borderColor: C.borderOn,
  },
  poolChipOn: { backgroundColor: C.green, borderColor: 'transparent' },
  poolChipText: { ...T.tiny, color: C.muted },
  poolChipTextOn: { color: '#ffffff', fontFamily: 'Archivo_700Bold' },
  /* The members table, in the standings table's own numbers
     (league/[id]/draw/[drawId]/index.jsx): keep the two in step. */
  mScroller: { flex: 1, minHeight: 0, marginHorizontal: -S.lg },
  mRows: { backgroundColor: C.card },
  mRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 3, paddingHorizontal: S.lg, gap: 8 },
  mHead: { backgroundColor: C.raised, paddingVertical: 8, borderBottomWidth: 2, borderBottomColor: C.green },
  mHeadText: { color: C.muted, fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  mHeadOn: { color: C.greenBright },
  mAlt: { backgroundColor: '#14201c' },
  mMine: { backgroundColor: '#1d3329' },
  mWho: { flex: 1, minWidth: 0 },
  mName: { color: C.ink, fontWeight: '600', fontSize: 14, lineHeight: leading(17) },
  mNameMine: { color: C.clay, fontWeight: '800' },
  mReal: { color: C.muted, fontSize: 12, lineHeight: leading(15), marginTop: -leading(3) },
  mNum: { width: 46, textAlign: 'center' },
  mNumText: { color: C.muted, fontSize: 14 },
  mOn: { color: C.ink, fontWeight: '800' },
  adminBadge: { ...T.tiny, color: C.info, borderWidth: 1, borderColor: C.info, borderRadius: 4, paddingHorizontal: 4, overflow: 'hidden' },
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
  /* alignItems:'center' because TourBadge carries alignSelf:'flex-start' for
     the stacked layouts it usually sits in, which would pin these to the top
     of the card. The padding is the chevron's own, so the right edge is where
     it always was. */
  tours: {
    flexDirection: 'row', gap: 4, alignItems: 'center',
    alignSelf: 'center', paddingRight: 14,
  },
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
