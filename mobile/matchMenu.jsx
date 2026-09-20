/* WHAT A MATCH CAN OPEN, on a long press (owner, 2026-09-20).
 *
 * The schedule's dense rows carried a 24pt column down their right edge with
 * H2H above and the predictors' icon below — two permanent controls on every
 * row of a list whose job is to be read. Held rather than shown, the row gets
 * its width back and the actions get their real names.
 *
 * A SHEET RATHER THAN A FLOATING CARD. iOS's own answer to a long press is a
 * context menu pinned to the touch, and it is the better answer where it is
 * available — but it is UIKit's, reachable only through a native module this
 * app does not carry. The bottom sheet is what the project already uses for
 * every other held-open decision (rename.jsx), it needs no measurement of
 * where a finger landed, and it cannot open off the edge of the screen.
 *
 * THE SHEET WEARS THE MATCH'S TOUR (owner, 2026-09-20: bigger, and better
 * designed). A first pass was three small outlined pills of 15pt text, which
 * is a settings list, not a menu you called up with your thumb. The design
 * this one follows is the app's own: a tour-tinted eyebrow, the match named
 * in the condensed display face, its score in the scoreboard's green, and
 * the actions as ONE card of tall rows — each with its glyph on a plate in
 * the tour's colour, exactly as the tier badge wears its tour. A reader who
 * held the wrong row can see which match this is before they choose, which
 * is the header's real job.
 *
 * ONLY WHAT THIS MATCH HAS. A doubles pair with no Tennis Explorer slugs has
 * no head-to-head; an unplayed match has no point-by-point; a schedule row
 * with no match id has nobody's picks to show. Each action appears when its
 * data does, and a match with nothing to open never opens the menu at all —
 * see `actionsFor`, which the row asks before it arms the gesture.
 */
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { matchLine } from './matchLine'
import { C, R, S, T, TOUR } from './theme'
import { eyebrowType } from './ui'
import { leading } from './fontScale.js'

/* The actions a row offers, in the order a reader wants them: who is playing,
   then what other people think, then what happened. Returns [] when there is
   nothing — the caller uses that to leave the long press unarmed rather than
   opening an empty sheet. */
export function actionsFor({ pair, picks, openable, finished }) {
  const out = []
  if (pair) {
    out.push({
      key: 'h2h',
      label: 'Head to head',
      hint: 'Every meeting, and this season’s form',
      icon: 'git-compare',
    })
  }
  if (picks) {
    out.push({
      key: 'picks',
      label: finished ? 'Who called it' : 'Who’s still in it',
      hint: finished ? 'How your league picked this match' : 'Who your league has going through',
      icon: 'people',
    })
  }
  if (openable) {
    out.push({
      key: 'history',
      label: 'Point by point',
      hint: 'The score as it was played',
      icon: 'stats-chart',
    })
  }
  return out
}

const EYEBROW = eyebrowType({ small: true })

export function MatchMenu({ target, onClose, onH2H, onPredictors, onHistory }) {
  const insets = useSafeAreaInsets()
  if (!target) return null
  const { e, pair, picks, openable } = target
  const actions = actionsFor({ pair, picks, openable, finished: e.winner_side != null })
  const line = matchLine(e)
  /* The tour's own colours, as the card and the tier badge take them. A
     doubles row carries no gender, so `tour` is the fallback — and a mixed
     event is neither, which is what the neutral plate is for. */
  const key = e.gender || (e.tour === 'WTA' ? 'F' : e.tour === 'ATP' ? 'M' : null)
  const tint = TOUR[key] || { plate: C.sunken, text: C.greenLit, label: null }

  const run = (k) => {
    onClose()
    if (k === 'h2h') onH2H(pair)
    else if (k === 'picks') onPredictors(target.match)
    else if (k === 'history') onHistory(e)
  }

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <View style={s.fill}>
        <Pressable style={s.scrim} onPress={onClose} accessibilityLabel="Close" />
        {/* The sheet clears the home indicator rather than sitting on it. */}
        <View style={[s.sheet, { paddingBottom: Math.max(S.md, insets.bottom + S.xs) }]}>
          <View style={s.grabber} />

          <View style={s.head}>
            <Text style={[EYEBROW.style, { letterSpacing: EYEBROW.track, color: tint.text }]}
                  numberOfLines={1}>
              {[tint.label, e.tournament_name, line.round].filter(Boolean).join('  ·  ')}
            </Text>
            <Text style={s.names} numberOfLines={2}>{line.names}</Text>
            {line.score ? <Text style={s.score}>{line.score}</Text> : null}
          </View>

          {/* ONE CARD, hairline-divided: three separate pills read as three
              unrelated things, and this is one set of choices about one
              match. A tall row — 60pt against Apple's 44 — because a sheet
              is the one place in this app with room to be generous. */}
          <ScrollView style={s.menuWrap} contentContainerStyle={s.menu} bounces={false}>
            {actions.map((a, i) => (
              <Pressable key={a.key}
                         style={({ pressed }) => [s.action, i > 0 && s.actionNext, pressed && s.actionPressed]}
                         onPress={() => run(a.key)}
                         accessibilityRole="button" accessibilityLabel={a.label}
                         accessibilityHint={a.hint}>
                <View style={[s.slot, { backgroundColor: tint.plate }]}>
                  <Ionicons name={a.icon} size={22} color={tint.text} />
                </View>
                <View style={s.labels}>
                  <Text style={s.label}>{a.label}</Text>
                  <Text style={s.hint} numberOfLines={1}>{a.hint}</Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={C.faint} />
              </Pressable>
            ))}
          </ScrollView>

          <Pressable style={({ pressed }) => [s.cancel, pressed && s.actionPressed]}
                     onPress={onClose} accessibilityRole="button">
            <Text style={s.cancelText}>Cancel</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  )
}

const s = StyleSheet.create({
  fill: { flex: 1, justifyContent: 'flex-end' },
  scrim: { flex: 1, backgroundColor: '#000b' },
  sheet: {
    backgroundColor: C.card,
    borderTopLeftRadius: 22, borderTopRightRadius: 22,
    borderTopWidth: 1, borderColor: C.border,
    paddingHorizontal: S.md, paddingTop: S.sm, gap: S.md,
  },
  grabber: { width: 40, height: 4, borderRadius: 2, backgroundColor: C.border, alignSelf: 'center' },

  // The match, named the way the app names things: condensed display face,
  // the score in the scoreboard's green under it.
  head: { alignItems: 'center', gap: 2, paddingHorizontal: S.xs },
  names: {
    fontFamily: 'SairaCondensed_700Bold', fontSize: 25, lineHeight: leading(29),
    color: C.ink, textAlign: 'center',
  },
  score: {
    fontFamily: 'SairaCondensed_700Bold', fontSize: 19, lineHeight: leading(22),
    color: C.greenMid, letterSpacing: 0.6,
  },

  // Tall enough that the sheet never scrolls at three actions, and able to
  // when a fourth is added or the reader's text is large.
  menuWrap: { maxHeight: 340, flexGrow: 0 },
  menu: {
    backgroundColor: C.sunken, borderRadius: R.lg,
    borderWidth: 1, borderColor: C.border, overflow: 'hidden',
  },
  action: { flexDirection: 'row', alignItems: 'center', gap: S.md, minHeight: 60, paddingHorizontal: S.md },
  // The divider is the row's own top edge, so the card keeps one outline.
  actionNext: { borderTopWidth: 1, borderTopColor: C.border },
  actionPressed: { backgroundColor: C.raised },
  slot: { width: 42, height: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  labels: { flex: 1, minWidth: 0, gap: 1 },
  label: { fontFamily: 'Archivo_500Medium', fontSize: 17, lineHeight: leading(22), color: C.ink },
  hint: { ...T.small, color: C.faint },

  cancel: {
    borderRadius: R.pill, borderWidth: 1, borderColor: C.borderOn,
    minHeight: 52, alignItems: 'center', justifyContent: 'center',
  },
  cancelText: { fontFamily: 'Archivo_700Bold', fontSize: 17, color: C.inkBody },
})
