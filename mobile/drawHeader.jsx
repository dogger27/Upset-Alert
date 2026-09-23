/* THE DRAW'S HEADER BAR: tour tint, the ATP/WTA switch (or the plain tier
 * pill), the name, and a full-height button on to the next draw being played.
 *
 * Shared by the Draw tab and a league's standings for one draw (owner,
 * 2026-09-23: "use the same header from the draw page in the league page, with
 * the next tournament button"). The bar only draws; where a tap goes is the
 * screen's business — the Draw tab steps to /draw/:id, the league page to its
 * own standings for that draw — so both destinations come in as callbacks.
 */
import { Ionicons } from '@expo/vector-icons'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { FONT_SCALE, leading } from './fontScale.js'
import { TourSwitch } from './cards'
import { C, R, S, T } from './theme'

export function DrawHeaderBar({ t, siblings, onPickSibling, next, onNext }) {
  return (
    <View style={s.head}>
      <View style={[s.tint, { backgroundColor: t.gender === 'F' ? C.wta : C.atp }]} />
      <View style={s.headBody}>
        {/* THE PAIR, AS A SWITCH. A combined event is two draws under
            one name, and the reader on one of them usually wants the
            other next — the standings screens already offer it this
            way, so the bracket does too. The tour being read wears the
            badge; the other is greyed and waiting to be pressed. One
            draw, and TourSwitch renders the plain badge it always did
            (owner, 2026-09-14).

            REPLACE, NOT PUSH: flipping tours is changing what you are
            looking at, not going somewhere new, and pushing would stack
            a back-button trail of the same event. setCurrentDraw keeps
            the Draw tab and the Schedule's default in step — the
            screen's own effect does it too, but not until the new route
            has mounted. */}
        {/* pairLevel={false}: with both tours up there the level is the
            same on both pills and the name is what is short of room. */}
        <TourSwitch draws={siblings} currentId={t.id} showLevel pairLevel={false}
                    style={{ alignSelf: 'center' }}
                    onPick={onPickSibling} />
        {/* THE NAME TAKES THE SLACK, so the step button sits hard
            against the right edge whatever the tournament is called,
            and the pill holds the left whatever its tier reads. */}
        <Text style={s.headName} numberOfLines={1}>{t.name}</Text>
      </View>
      {/* ON TO THE NEXT ONE BEING PLAYED. Not the old stepper arrows:
          those walked a list you could not see, one at a time, which is
          what the Draw tab's chooser replaced. This is one step through
          the draws that are actually live, it names its destination to a
          screen reader, and the chooser is still there for going
          anywhere.

          A SIBLING OF headBody, NOT A CHILD OF IT (owner, 2026-09-16: a
          button the full height of the bar). headBody carries the bar's
          horizontal padding, so a child could never reach the right edge
          and could never be taller than that padding allowed. Out here
          it is the tint stripe's opposite number — the stripe is a
          full-height block on the left and this is one on the right, and
          both take the bar's height for free because `head` is a row
          whose alignItems defaults to stretch. `head`'s overflow:hidden
          is what rounds its outer corner to the card's radius. */}
      {next && (
        <Pressable onPress={() => onNext(next)}
                   hitSlop={{ top: 9, bottom: 9 }} accessibilityRole="button"
                   accessibilityLabel={`Next draw: ${next.name} ${next.gender === 'F' ? 'WTA' : 'ATP'}`}
                   style={({ pressed }) => [s.cycle, pressed && { opacity: 0.6 }]}>
          <Ionicons name="chevron-forward" size={leading(20)} color={C.greenLit} />
        </Pressable>
      )}
    </View>
  )
}

const s = StyleSheet.create({
  head: {
    flexDirection: 'row', backgroundColor: C.card, borderRadius: R.md,
    borderWidth: 1, borderColor: C.border, overflow: 'hidden',
  },
  tint: { width: 4 },
  /* One row of one line, so it is padded like a header bar rather than a
     card: S.md across and 2pt down — S.xs was still a touch generous for a
     single line (owner, 2026-09-08), and the title's line box is trimmed
     to match, so the banner is as tall as its name and no more. */
  /* minHeight, AND IT IS LOAD-BEARING NOW. The bar used to be as tall as its
     tallest child, and that child was the 24pt circle — so pulling the button
     out of this row would have SHRUNK the bar it is meant to fill. This gives
     the bar a height it chose rather than one it inherited, and leading() so
     it grows with the reader instead of cropping the name. */
  headBody: {
    flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingHorizontal: S.md, paddingVertical: 0, minHeight: leading(26),
  },
  /* The line box is the type's own height: 19pt Saira Condensed needs no
     more than 19 of line, so the banner is exactly the name plus the
     badge's own padding. */
  /* Nudged DOWN, measured off the phone: with the line box at the type's
     own height iOS sets the caps ~1.5pt above the centre of it, and in a
     banner this short that reads as the name floating. A transform, so
     the banner's height is untouched. */
  /* THE BAR'S FULL HEIGHT, and no ring (owner, 2026-09-16). What the ring was
     doing — saying "this is a control" — the block now does better: a filled
     panel on the bar's right edge, the tint stripe's opposite number.
     NO alignSelf and NO height: `head` is a row, its alignItems defaults to
     stretch, so the block takes the bar's height whatever the reader's text
     size makes it. Stating a height here would be the one way to get this
     wrong.
     greenDeep AND greenLit ARE ROUNDSTRIP'S OWN PAIR — the fill and edge of
     the round pager's selected pill, which is this app's established "a green
     block is a control you press". The fill alone is 1.17:1 against the bar,
     so it tints rather than separates; the left border at 5.46:1 is what
     actually cuts the block out of the bar, which is why the owner asked for
     both. A brighter fill was the alternative and it costs more than it buys:
     C.green reads at 2.48:1 but drops the arrow on it from 5.46 to 2.58. */
  cycle: {
    paddingHorizontal: S.sm, alignItems: 'center', justifyContent: 'center',
    backgroundColor: C.greenDeep,
    borderLeftWidth: 1, borderLeftColor: C.greenLit,
  },
  headName: {
    ...T.h2, lineHeight: leading(19), color: C.ink, flex: 1,
    transform: [{ translateY: 1.5 * FONT_SCALE }],
  },
})
