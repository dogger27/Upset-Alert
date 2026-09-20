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
 * ONLY WHAT THIS MATCH HAS. A doubles pair with no Tennis Explorer slugs has
 * no head-to-head; an unplayed match has no point-by-point; a schedule row
 * with no match id has nobody's picks to show. Each action appears when its
 * data does, and a match with nothing to open never opens the menu at all —
 * see `actionsFor`, which the row asks before it arms the gesture.
 */
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { matchLine } from './matchLine'
import { C, R, S, T } from './theme'

/* The actions a row offers, in the order a reader wants them: who is playing,
   then what other people think, then what happened. Returns [] when there is
   nothing — the caller uses that to leave the long press unarmed rather than
   opening an empty sheet. */
export function actionsFor({ pair, picks, openable, finished }) {
  const out = []
  if (pair) out.push({ key: 'h2h', label: 'Head to head', icon: 'git-compare-outline' })
  if (picks) {
    out.push({
      key: 'picks',
      label: finished ? 'Who called it' : 'Who’s still in it',
      icon: 'people-outline',
    })
  }
  if (openable) out.push({ key: 'history', label: 'Point by point', icon: 'stats-chart-outline' })
  return out
}

export function MatchMenu({ target, onClose, onH2H, onPredictors, onHistory }) {
  if (!target) return null
  const { e, pair, picks, openable } = target
  const actions = actionsFor({ pair, picks, openable, finished: e.winner_side != null })
  const line = matchLine(e)
  const run = (key) => {
    onClose()
    if (key === 'h2h') onH2H(pair)
    else if (key === 'picks') onPredictors(target.match)
    else if (key === 'history') onHistory(e)
  }
  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <View style={s.fill}>
        <Pressable style={s.scrim} onPress={onClose} accessibilityLabel="Close" />
        <View style={s.sheet}>
          <View style={s.grabber} />
          {/* The match names itself, so the sheet needs no title of its own —
              and a reader who long-pressed the wrong row can see that here. */}
          <Text style={s.head} numberOfLines={2}>{line.names}</Text>
          {e.tournament_name || e.round_label ? (
            <Text style={s.sub}>
              {[e.tournament_name, e.round_label].filter(Boolean).join(' · ')}
            </Text>
          ) : null}
          <View style={s.actions}>
            {actions.map(a => (
              <Pressable key={a.key} style={s.action} onPress={() => run(a.key)}
                         accessibilityRole="button" accessibilityLabel={a.label}>
                <Ionicons name={a.icon} size={18} color={C.greenLit} />
                <Text style={s.actionText}>{a.label}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable style={s.cancel} onPress={onClose} accessibilityRole="button">
            <Text style={s.cancelText}>Cancel</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  )
}

const s = StyleSheet.create({
  fill: { flex: 1, justifyContent: 'flex-end' },
  scrim: { flex: 1, backgroundColor: '#000a' },
  sheet: {
    backgroundColor: C.card, borderTopLeftRadius: 18, borderTopRightRadius: 18,
    borderTopWidth: 1, borderColor: C.border,
    paddingHorizontal: S.md, paddingTop: S.sm, paddingBottom: S.lg, gap: S.sm,
  },
  grabber: { width: 36, height: 4, borderRadius: 2, backgroundColor: C.border, alignSelf: 'center', marginBottom: S.xs },
  head: { ...T.bodyBold, color: C.ink, textAlign: 'center' },
  sub: { ...T.tiny, color: C.muted, textAlign: 'center', marginTop: -S.xs },
  actions: { gap: S.xs, marginTop: S.xs },
  /* A row per action, tall enough to hit without looking: TOUCH is Apple's
     44 and the sheet is the one place in this app with room for it. */
  action: {
    flexDirection: 'row', alignItems: 'center', gap: S.sm,
    minHeight: 44, paddingHorizontal: S.sm,
    borderRadius: R.md, backgroundColor: C.sunken,
    borderWidth: 1, borderColor: C.border,
  },
  actionText: { ...T.bodyMed, color: C.ink },
  cancel: { borderRadius: R.pill, borderWidth: 1, borderColor: C.border, paddingVertical: 12, alignItems: 'center' },
  cancelText: { ...T.bodyBold, color: C.inkBody },
})
