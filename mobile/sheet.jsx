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
export function Sheet({ visible, onClose, title, titleRight, children, height }) {
  return (
    <Modal visible={!!visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose} accessibilityLabel="Close" />
      <View style={[s.sheet, height ? { height } : null]}>
        <View style={s.grabber} />
        {/* A TITLE WITH CONTROLS BESIDE IT CANNOT STAY CENTRED. Centring
            measures the title against the whole width, so an accessory on the
            right pushes the words off-centre by half its size — the heading
            drifts left as the buttons grow. With `titleRight` the row splits
            properly: title left, controls right, each honestly aligned to its
            own edge. Without it, nothing changes for the sheets that have
            only a heading. */}
        {title ? (
          titleRight ? (
            <View style={s.titleRow}>
              {/* SHRINKS, NEVER TRUNCATES. "Select Tournament(s)" beside two
                  controls is already close to the width of a phone, and it
                  runs out of room outright at a large text size — where an
                  ellipsis would eat the word that says what the sheet is for.
                  Same ladder the bracket's names use: make it fit. */}
              <Text style={[s.title, s.titleLeft]} numberOfLines={1}
                    adjustsFontSizeToFit minimumFontScale={0.75}>{title}</Text>
              {titleRight}
            </View>
          ) : <Text style={s.title}>{title}</Text>
        ) : null}
        {children}
        {/* THE FOOTER IS ITS OWN SECTION, and now says so (owner, 2026-09-23:
            "put a thin line / upper border / divider on the bottom screen
            section where the Close button is"). A sheet whose content scrolls
            ends wherever the scroll happens to stop — half a row of buttons,
            in the case that prompted this — and with nothing between that and
            Close the clipped content read as broken rather than as scrollable.

            The line spans the whole sheet, not the button: negative margins
            cancel the sheet's own horizontal padding, which is what makes a
            divider read as the edge of a section instead of an underline on a
            word. Every sheet in the app gets it, because every sheet has this
            row. */}
        <View style={s.footer}>
          <Pressable onPress={onClose} style={s.close} hitSlop={8}>
            <Text style={s.closeText}>Close</Text>
          </Pressable>
        </View>
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
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  titleLeft: { flex: 1, textAlign: 'left' },
  footer: {
    marginHorizontal: -S.md, paddingHorizontal: S.md, alignItems: 'center',
    borderTopWidth: 1, borderTopColor: C.border,
  },
  close: { alignSelf: 'center', paddingVertical: S.sm, paddingHorizontal: S.lg },
  closeText: { ...T.smallMed, color: C.clay },
})
