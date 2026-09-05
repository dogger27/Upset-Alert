/* The bottom sheet every "ask the user something" surface shares — H2H,
   predictors, create/join a league, invite. One place, so they all open, dim
   and close the same way. */
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native'
import { C, S, T } from './theme'

/* `height` fixes the sheet's height instead of letting it size to its content.
   Only worth passing when the content CHANGES height while open — the score
   history's tabs swap panels with different row counts, and a bottom sheet
   grows upward, so without this the timeline slid up the screen as the reader
   switched tabs. Everything else leaves it off and keeps hugging its content. */
export function Sheet({ visible, onClose, title, children, height }) {
  return (
    <Modal visible={!!visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose} accessibilityLabel="Close" />
      <View style={[s.sheet, height ? { height } : null]}>
        <View style={s.grabber} />
        {title ? <Text style={s.title}>{title}</Text> : null}
        {children}
        <Pressable onPress={onClose} style={s.close} hitSlop={8}>
          <Text style={s.closeText}>Close</Text>
        </Pressable>
      </View>
    </Modal>
  )
}

const s = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: '#000a' },
  sheet: {
    backgroundColor: C.card, borderTopLeftRadius: 18, borderTopRightRadius: 18,
    borderTopWidth: 1, borderColor: C.border,
    paddingHorizontal: S.md, paddingTop: S.sm, paddingBottom: S.lg, gap: S.sm,
    maxHeight: '80%',
  },
  grabber: { width: 36, height: 4, borderRadius: 2, backgroundColor: C.border, alignSelf: 'center', marginBottom: S.xs },
  title: { ...T.h2, color: C.ink, textAlign: 'center' },
  close: { alignSelf: 'center', paddingVertical: S.sm, paddingHorizontal: S.lg },
  closeText: { ...T.smallMed, color: C.clay },
})
