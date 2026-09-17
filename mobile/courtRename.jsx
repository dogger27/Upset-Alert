/* RENAME A COURT — the admin's sheet on the schedule's court view.
 *
 * The name typed here is the court's display name everywhere the schedule is
 * served: the site, the app, anything else that reads the API (the server
 * swaps it in; nothing here knows more than that). The sheet's own name stays
 * the key and is shown beneath the field so the admin can see what they are
 * renaming; clearing the field, or "Use the sheet's name", puts it back. */
import { useEffect, useState } from 'react'
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { setCourtAlias } from './api'
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
