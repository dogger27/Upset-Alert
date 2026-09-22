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
import { useState } from 'react'
import { Alert, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { FitText } from './cards'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { hideFromLockScreen, showMatchOnLockScreen, useShowingOnLockScreen } from './liveactivity'
import { isAvailable as lockScreenAvailable } from './modules/live-activity'
import { matchLine } from './matchLine'
import { isLive } from './schedule'
import { showToast } from './toast'
import { C, R, S, T, TOUR } from './theme'
import { eyebrowType } from './ui'
import { leading } from './fontScale.js'

/* The actions a row offers, in the order a reader wants them: who is playing,
   then what other people think, then what happened. Returns [] when there is
   nothing — the caller uses that to leave the long press unarmed rather than
   opening an empty sheet. */
export function actionsFor({ pair, picks, openable, finished, lock, lockOn }) {
  const out = []
  /* THE LOCK SCREEN FIRST (owner, 2026-09-22), because it is the only one of
     these that acts rather than opens: the others show you something about
     the match, this one puts the match somewhere. It is also the one with a
     live window — a match you can watch right now — so it belongs where a
     thumb lands first.

     `lock` is whether it is OFFERED and `lockOn` whether it is already there,
     which only changes the wording. The row asks actionsFor with lockOn
     unknown, purely to decide whether to arm the long press at all, and the
     count is the same either way. */
  if (lock) {
    out.push({
      key: 'lock',
      label: lockOn ? 'Remove from Lock Screen' : 'Show Score on Lock Screen',
      hint: lockOn ? 'Stop the live score there' : 'The live score, without unlocking',
      icon: lockOn ? 'lock-open' : 'lock-closed',
    })
  }
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
  /* BEFORE THE EARLY RETURN, because it is a hook. It takes a null id — the
     sheet is mounted with no target most of the time — and answers false. */
  const [onLockScreen, recheckLock] = useShowingOnLockScreen(target?.e?.match_id)
  const [lockBusy, setLockBusy] = useState(false)
  if (!target) return null
  const { e, pair, picks, openable } = target
  /* OFFERED ON THE SAME MATCHES AS THE SCHEDULE'S OWN LOCK CHIP: a match we
     hold an id for, on a build with the native module, that is either running
     or already up there. A finished match that is not showing has nothing to
     put on a Lock Screen — the end push retires its activity by itself. */
  const lock = !!(lockScreenAvailable() && e.match_id != null
                  && (onLockScreen || isLive(e)))
  const actions = actionsFor({ pair, picks, openable, finished: e.winner_side != null,
                              lock, lockOn: onLockScreen })
  const line = matchLine(e)
  /* The tour's own colours, as the card and the tier badge take them. A
     doubles row carries no gender, so `tour` is the fallback — and a mixed
     event is neither, which is what the neutral plate is for. */
  const key = e.gender || (e.tour === 'WTA' ? 'F' : e.tour === 'ATP' ? 'M' : null)
  const tint = TOUR[key] || { plate: C.sunken, text: C.greenLit, label: null }

  /* THE ONE ACTION THAT DOES NOT CLOSE FIRST. The others hand off to a sheet;
     this one awaits the system and can fail, and a menu that vanished before
     the failure would leave the error with nothing to explain it. So it
     reports, then closes. Guarded against a double tap, as the schedule's
     chip is. */
  const toggleLock = async () => {
    if (lockBusy) return
    setLockBusy(true)
    try {
      if (onLockScreen) {
        await hideFromLockScreen(e.match_id)
        showToast('Removed from the Lock Screen')
      } else {
        await showMatchOnLockScreen(e.match_id)
        showToast('Now showing on the Lock Screen')
      }
      onClose()
    } catch (err) {
      Alert.alert('Lock Screen', err?.message || 'Could not change the Lock Screen')
    } finally {
      setLockBusy(false)
      recheckLock()
    }
  }

  const run = (k) => {
    if (k === 'lock') { toggleLock(); return }
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
            {/* THE COURT, ON ITS OWN LINE UNDER THE TOURNAMENT (owner,
                2026-09-22). The header's job is to prove which match you are
                holding, and on a day where one tournament has four courts the
                two names are not always enough to tell — so the place is part
                of the identification. Quiet, because it is the last thing you
                check and never the first.

                Only when there is one: a draw-screen match carries no court,
                and an empty line under the eyebrow would read as a failure to
                load one. The alias an admin set is already in this field, the
                server having resolved it (display_court). */}
            {e.court ? (
              <Text style={s.court} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
                {String(e.court).toUpperCase()}
              </Text>
            ) : null}
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
                  {/* ONE LINE, ALWAYS (owner, 2026-09-22). "Remove from Lock
                      Screen" wrapped to two and pushed its own hint down the
                      row, so one command was a head taller than the rest and
                      the card stopped reading as a set. FitText shrinks it to
                      the width it has instead — measured from the font's own
                      metrics, no ellipsis, which is this project's rule for
                      text that must not be cut. The floor is 13pt: below that
                      a 17pt row's label stops matching its neighbours more
                      than a wrap did. */}
                  <FitText style={s.label} min={13}>{a.label}</FitText>
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
  // Between the tinted eyebrow and the match-up, and quieter than both.
  court: { ...T.tiny, color: C.faint, textAlign: 'center', letterSpacing: 0.5 },
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
