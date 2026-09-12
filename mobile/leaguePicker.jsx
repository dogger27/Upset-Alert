/*
 * Changing which league you are reading, from the league's own name.
 *
 * The Leagues tab no longer opens a list — it opens the league last read — so
 * this is the way to the others. The heading IS the control: a larger league
 * name with a chevron under it, which is the pattern people already know from
 * the draw chooser on the tab bar.
 *
 * The sheet lists the leagues and nothing else except one row out to the full
 * screen, because creating and joining are FORMS and they already exist there.
 * Two implementations of "enter an invite code" would be one too many.
 */
import { router } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { getLeagues } from './api'
import { setLastLeague } from './lastLeague'
import { Sheet } from './sheet'
import { useApi } from './useApi'
import { C, T } from './theme'

/* The heading, as a button. Bigger than the navigation title it replaces —
   this is the name of the thing you are reading AND the way to read another,
   so it earns the size. */
export function LeagueTitle({ name, onPress }) {
  return (
    <Pressable onPress={onPress} hitSlop={10} accessibilityRole="button"
               accessibilityLabel={`${name || 'League'} — change league`}
               style={({ pressed }) => [s.title, pressed && { opacity: 0.6 }]}>
      <Text style={s.titleText} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
        {name || 'League'}
      </Text>
      <Ionicons name="chevron-down" size={18} color={C.muted} style={{ marginTop: 2 }} />
    </Pressable>
  )
}

export function LeaguePicker({ visible, onClose, currentId }) {
  // Only fetched while the sheet is open: the list is already in the cache from
  // the tab in most cases, and a closed sheet has no business polling.
  const { data: leagues } = useApi(visible ? 'leagues' : null, getLeagues, { enabled: visible })

  const go = id => {
    onClose()
    if (Number(id) === Number(currentId)) return
    setLastLeague(id)
    // replace, not push: choosing another league is a change of subject, not a
    // step deeper — Back should still return where the reader came from rather
    // than walking them through every league they looked at.
    router.replace(`/league/${id}`)
  }

  return (
    <Sheet visible={visible} onClose={onClose} title="Leagues">
      {(leagues ?? []).map(lg => (
        <Pressable key={lg.id} style={s.row} onPress={() => go(lg.id)}
                   accessibilityRole="button">
          <View style={{ flex: 1 }}>
            <Text style={s.name} numberOfLines={1}>{lg.name}</Text>
            <Text style={s.sub}>
              {lg.member_count === 1 ? '1 member' : `${lg.member_count} members`}
            </Text>
          </View>
          {Number(lg.id) === Number(currentId)
            ? <Ionicons name="checkmark" size={16} color={C.greenBright} />
            : null}
        </Pressable>
      ))}
      <Pressable style={s.row} onPress={() => { onClose(); router.push('/leagues') }}
                 accessibilityRole="button">
        <Text style={[s.name, { color: C.greenLit, flex: 1 }]}>Create or join a league</Text>
        <Ionicons name="chevron-forward" size={16} color={C.greenLit} />
      </Pressable>
    </Sheet>
  )
}

const s = StyleSheet.create({
  /* 200, not more: the title is centred and "< Back" sits to its left, so a
     long league name that grew into it would collide rather than shrink.
     adjustsFontSizeToFit does the shrinking inside this box. */
  title: { flexDirection: 'row', alignItems: 'center', gap: 6, maxWidth: 200 },
  // h1 rather than the h2 a navigation title would use — the owner asked for
  // larger, and it has to read as tappable next to a plain Back button.
  titleText: { ...T.h1, color: C.ink, flexShrink: 1 },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingVertical: 12, borderTopWidth: 1, borderTopColor: C.border,
  },
  name: { ...T.bodyMed, color: C.ink },
  sub: { ...T.tiny, color: C.muted },
})
