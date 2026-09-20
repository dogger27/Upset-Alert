/* THE ADMIN'S RENAME SHEETS on the schedule — a court, and an event.
 *
 * Both live here because they are one sheet with different fields, and a
 * second copy of the bottom-sheet chrome (the scrim, the grabber, the rise
 * with the keyboard, the buttons) is a second copy to keep in step. The
 * styles at the foot are shared.
 *
 * RENAME A COURT — the sheet on the schedule's court view.
 *
 * The name typed here is the court's display name everywhere the schedule is
 * served: the site, the app, anything else that reads the API (the server
 * swaps it in; nothing here knows more than that). The sheet's own name stays
 * the key and is shown beneath the field so the admin can see what they are
 * renaming; clearing the field, or "Use the sheet's name", puts it back. */
import { useEffect, useState } from 'react'
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { setCourtAlias, setTournamentName } from './api'
import { invalidate } from './useApi'
import { C, S, T } from './theme'

export function CourtRenameSheet({ court, onClose }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  useEffect(() => { setName(court?.current || ''); setError(null) }, [court])
  if (!court) return null
  const aliased = court.current !== court.court_key
  const save = async (value) => {
    setBusy(true); setError(null)
    try {
      await setCourtAlias(court.tournament_id, court.court_key, value)
      // The day's rows carry the display name; refetch them and the header follows.
      invalidate('schedule:')
      onClose()
    } catch (e) {
      setError(e?.message || 'Could not rename the court.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      {/* THE SHEET RISES WITH THE KEYBOARD. The field focuses itself, so the
          keyboard is up before the sheet has settled, and a bottom sheet
          under it is a sheet nobody can see (owner, 2026-09-17). On iOS the
          container pads by the keyboard's height; Android resizes the window
          itself. */}
      <KeyboardAvoidingView style={s.fill} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Pressable style={s.scrim} onPress={onClose} accessibilityLabel="Close" />
      <View style={s.sheet}>
        <View style={s.grabber} />
        <Text style={s.title}>Rename court</Text>
        <Text style={s.key}>On the sheet: {court.court_key}</Text>
        <TextInput
          style={s.input} value={name} onChangeText={setName} autoFocus
          placeholder="Display name" placeholderTextColor={C.muted}
          autoCapitalize="words" autoCorrect={false} returnKeyType="done"
          onSubmitEditing={() => save(name)} editable={!busy}
          accessibilityLabel="Court display name"
        />
        {error ? <Text style={s.err}>{error}</Text> : null}
        <Pressable style={[s.btn, s.primary, busy && s.dim]} onPress={() => save(name)} disabled={busy}
                   accessibilityRole="button">
          {busy ? <ActivityIndicator color={C.bg} /> : <Text style={s.primaryText}>Save everywhere</Text>}
        </Pressable>
        {aliased && (
          <Pressable style={[s.btn, busy && s.dim]} onPress={() => save('')} disabled={busy} accessibilityRole="button">
            <Text style={s.btnText}>{'Use the sheet\u2019s name'}</Text>
          </Pressable>
        )}
        <Pressable style={s.btn} onPress={onClose} accessibilityRole="button">
          <Text style={s.btnText}>Cancel</Text>
        </Pressable>
      </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

/* RENAME AN EVENT — two names, one row (owner, 2026-09-20).
 *
 *   The name        what a reader is shown wherever the event is named.
 *   Short name      the same event where there is no room for its name — a
 *                   chip, a row's tag, a strip across a phone. THE BOX HOLDS
 *                   THE REAL TEXT, default and all (owner, 2026-09-20): a
 *                   placeholder here was the wrong call — an empty field
 *                   reads as nothing set, and an editor wants to correct a
 *                   word, not retype it from scratch.
 *
 *                   Prefilling is safe because the server does not store a
 *                   short name that merely restates the default: save
 *                   "Korea" for Korea Open and nothing is written, so it
 *                   keeps following the name. Clearing the box does the same
 *                   thing explicitly.
 *
 * The SCRAPED name is shown beneath the fields and is never edited: it is
 * what the scrapers write and what the feed matchers compare against, so an
 * edit to it would both be undone by the next sync and change which event a
 * row resolves to. Clearing the field, or "Use the scraped name", drops the
 * override and that name shows through again.
 */
export function TournamentRenameSheet({ event, onClose }) {
  const [name, setName] = useState('')
  const [short, setShort] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  useEffect(() => {
    setName(event?.current || '')
    // The one in use — the admin's, or the default off the name — because a
    // box you can read and edit beats a box you have to guess at.
    setShort(event?.short || '')
    setError(null)
  }, [event])
  if (!event) return null
  const overridden = !!event.current && event.current !== event.scraped
  const save = async (value, shortValue) => {
    setBusy(true); setError(null)
    try {
      await setTournamentName(event.tournament_id, value, shortValue)
      // The day's rows carry the shown name; refetch them and the headings follow.
      invalidate('schedule:')
      onClose()
    } catch (e) {
      setError(e?.message || 'Could not rename the tournament.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView style={s.fill} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Pressable style={s.scrim} onPress={onClose} accessibilityLabel="Close" />
      <View style={s.sheet}>
        <View style={s.grabber} />
        <Text style={s.title}>Rename tournament</Text>
        <TextInput
          style={s.input} value={name} onChangeText={setName} autoFocus
          placeholder="Name" placeholderTextColor={C.muted}
          autoCapitalize="words" autoCorrect={false} returnKeyType="next"
          editable={!busy} accessibilityLabel="Tournament name"
        />
        <TextInput
          style={s.input} value={short} onChangeText={setShort}
          placeholder="Short name" placeholderTextColor={C.muted}
          autoCapitalize="words" autoCorrect={false} returnKeyType="done"
          onSubmitEditing={() => save(name, short)} editable={!busy}
          accessibilityLabel="Short tournament name"
        />
        <Text style={s.key}>As scraped: {event.scraped}</Text>
        {error ? <Text style={s.err}>{error}</Text> : null}
        <Pressable style={[s.btn, s.primary, busy && s.dim]} onPress={() => save(name, short)} disabled={busy}
                   accessibilityRole="button">
          {busy ? <ActivityIndicator color={C.bg} /> : <Text style={s.primaryText}>Save</Text>}
        </Pressable>
        {overridden && (
          <Pressable style={[s.btn, busy && s.dim]} onPress={() => save('', short)} disabled={busy} accessibilityRole="button">
            <Text style={s.btnText}>Use the scraped name</Text>
          </Pressable>
        )}
        <Pressable style={s.btn} onPress={onClose} accessibilityRole="button">
          <Text style={s.btnText}>Cancel</Text>
        </Pressable>
      </View>
      </KeyboardAvoidingView>
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
  title: { ...T.h2, color: C.ink, textAlign: 'center' },
  key: { ...T.tiny, color: C.muted, textAlign: 'center' },
  input: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12, height: 44, fontSize: 16, color: C.ink },
  btn: { borderRadius: 999, borderWidth: 1, borderColor: C.border, paddingVertical: 12, alignItems: 'center' },
  btnText: { ...T.bodyBold, color: C.inkBody },
  primary: { backgroundColor: C.greenLit, borderColor: C.greenLit },
  primaryText: { ...T.bodyBold, color: C.bg },
  dim: { opacity: 0.6 },
  err: { ...T.tiny, color: C.bad, textAlign: 'center' },
})
