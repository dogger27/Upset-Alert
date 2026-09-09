/*
 * The scoreboard's motion — the site's index.css keyframes, in Animated.
 *
 * Four things move here and each is the quietest it can be for what it
 * marks: a POINT bumps the number that changed; a GAME, a SET and a MATCH
 * pulse the card, each louder and longer than the one below; a CHAMPION
 * turns the card through the spectrum while a fanfare covers the screen;
 * and a STANDOUT chip — you called it, most of the field did not — arrives
 * with a shake and a neon ring.
 *
 * The site does the rings with box-shadow and the colour lifts with CSS
 * filters. Neither exists here, so a ring is its own View around the card
 * (border and glow), a "brighten" is a white veil at low opacity, and a
 * colour cycle is an interpolated border colour. Transforms and opacities
 * run on the native driver; the colour cycles run on the JS thread, which
 * is why they live on separate Animated nodes — mixing drivers on one node
 * is an error, not a slowdown.
 */
import { useEffect, useRef } from 'react'
import { Animated, Easing, StyleSheet, View } from 'react-native'
import { BUMP_MS, FX_MS, useReduceMotion } from './scoreFx'
import { PICK } from './theme'

const EASE = Easing.bezier(0.22, 0.7, 0.15, 1)

/* ── A point ───────────────────────────────────────────────────────────────
   The site's score-bump: up to 1.55×, brighter, held, then back — 2600ms,
   in step with useFlashOnChange's timer. */
export function Bump({ on, children, style }) {
  const reduce = useReduceMotion()
  const scale = useRef(new Animated.Value(1)).current
  const veil = useRef(new Animated.Value(0)).current
  useEffect(() => {
    if (!on) return
    scale.setValue(1); veil.setValue(0)
    const up = BUMP_MS * 0.08, hold = BUMP_MS * 0.30, down = BUMP_MS * 0.62
    const anim = Animated.parallel([
      reduce ? Animated.delay(0) : Animated.sequence([
        Animated.timing(scale, { toValue: 1.55, duration: up, easing: EASE, useNativeDriver: true }),
        Animated.delay(hold),
        Animated.timing(scale, { toValue: 1, duration: down, easing: EASE, useNativeDriver: true }),
      ]),
      Animated.sequence([
        Animated.timing(veil, { toValue: 0.35, duration: up, useNativeDriver: true }),
        Animated.delay(hold),
        Animated.timing(veil, { toValue: 0, duration: down, useNativeDriver: true }),
      ]),
    ])
    anim.start()
    return () => anim.stop()
  }, [on, reduce, scale, veil])
  return (
    <Animated.View style={[style, { transform: [{ scale }] }]}>
      {children}
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, s.veil, { opacity: veil }]} />
    </Animated.View>
  )
}

/* ── The escalating tiers, on a card ──────────────────────────────────────
   game: one firm pulse of the brand edge.
   set: twice the lift, two pulses, the card lifts with it.
   match: a wobble, a hold, and a ring that walks the spectrum.
   champion: the card spins through the spectrum for ten seconds.
   The ring is a sibling View drawn around the children; the card's own
   border stays underneath it so nothing reflows — a celebration may grow
   over its neighbours but may not move them. */
const RING = {
  game: ['#35785a', '#35785a'],
  set: [PICK.correct.border, PICK.correct.border],
  match: ['#ff2d95', '#ffd400', '#39ff14', '#00e5ff', '#b026ff', '#ff2d95'],
  champion: ['#ffd60a', '#ff2d95', '#39ff14', '#00e5ff', '#ffd60a', '#ff2d95', '#ffd60a'],
}
const LIFT = { game: 1.022, set: 1.045, match: 1.06, champion: 1.14 }
const WOBBLE = { game: 0, set: 0.5, match: 1.5, champion: 3 }

export function TierFx({ fx, radius = 12, children, style }) {
  const reduce = useReduceMotion()
  const scale = useRef(new Animated.Value(1)).current
  const rot = useRef(new Animated.Value(0)).current      // degrees
  const ring = useRef(new Animated.Value(0)).current     // 0..1 opacity
  const hue = useRef(new Animated.Value(0)).current      // 0..1 along RING[fx]
  useEffect(() => {
    if (!fx) return
    const ms = FX_MS[fx]
    scale.setValue(1); rot.setValue(0); ring.setValue(0); hue.setValue(0)
    const lift = LIFT[fx], wob = WOBBLE[fx]
    const pulses = fx === 'game' ? 1 : fx === 'set' ? 2 : 3
    const seg = (ms * 0.6) / pulses
    const bounce = Array.from({ length: pulses }, (_, i) => Animated.parallel([
      Animated.sequence([
        Animated.timing(scale, { toValue: lift, duration: seg * 0.3, easing: EASE, useNativeDriver: true }),
        Animated.timing(scale, { toValue: 1 + (lift - 1) * 0.45, duration: seg * 0.7, easing: EASE, useNativeDriver: true }),
      ]),
      Animated.sequence([
        Animated.timing(rot, { toValue: (i % 2 ? 1 : -1) * wob, duration: seg * 0.3, easing: EASE, useNativeDriver: true }),
        Animated.timing(rot, { toValue: (i % 2 ? -1 : 1) * wob * 0.6, duration: seg * 0.7, easing: EASE, useNativeDriver: true }),
      ]),
    ]))
    const motion = reduce ? Animated.delay(ms) : Animated.sequence([
      ...bounce,
      Animated.parallel([
        Animated.timing(scale, { toValue: 1, duration: ms * 0.4, easing: EASE, useNativeDriver: true }),
        Animated.timing(rot, { toValue: 0, duration: ms * 0.4, easing: EASE, useNativeDriver: true }),
      ]),
    ])
    const glow = Animated.sequence([
      Animated.timing(ring, { toValue: 1, duration: ms * 0.08, useNativeDriver: false }),
      Animated.delay(ms * 0.5),
      Animated.timing(ring, { toValue: 0, duration: ms * 0.42, useNativeDriver: false }),
    ])
    const cycle = Animated.timing(hue, { toValue: 1, duration: ms, easing: Easing.linear, useNativeDriver: false })
    const all = Animated.parallel([motion, glow, cycle])
    all.start()
    return () => all.stop()
  }, [fx, reduce, scale, rot, ring, hue])

  if (!fx) return <View style={style}>{children}</View>
  const colours = RING[fx]
  const borderColor = hue.interpolate({
    inputRange: colours.map((_, i) => i / (colours.length - 1)),
    outputRange: colours,
  })
  const rotate = rot.interpolate({ inputRange: [-10, 10], outputRange: ['-10deg', '10deg'] })
  return (
    <Animated.View style={[style, s.lifted, { transform: [{ scale }, { rotate }] }]}>
      {children}
      <Animated.View pointerEvents="none"
                     style={[s.ring, { borderRadius: radius + 3, borderColor, opacity: ring,
                                       shadowColor: borderColor }]} />
    </Animated.View>
  )
}

/* ── A champion ───────────────────────────────────────────────────────────
   Ten seconds of nonsense over the whole screen: trophies and crowns lead
   because they name the occasion; the rest is confetti and exists to fill
   the screen. pointerEvents none throughout — a celebration that blocks a
   tap is a ten-second outage. Unmounts when the tier clears. */
const TOKENS = ['🏆', '👑', '🥇', '⭐', '✨', '🎉', '🎊', '🌟', '💫', '🏅']
const PIECES = 36

function Piece({ token, x, delay, drift, spin, size }) {
  const t = useRef(new Animated.Value(0)).current
  useEffect(() => {
    const anim = Animated.loop(Animated.sequence([
      Animated.delay(delay),
      Animated.timing(t, { toValue: 1, duration: 3200 + (delay % 1400), easing: Easing.linear, useNativeDriver: true }),
      Animated.timing(t, { toValue: 0, duration: 0, useNativeDriver: true }),
    ]))
    anim.start()
    return () => anim.stop()
  }, [t, delay])
  const translateY = t.interpolate({ inputRange: [0, 1], outputRange: [-60, 900] })
  const translateX = t.interpolate({ inputRange: [0, 0.5, 1], outputRange: [0, drift, -drift * 0.4] })
  const rotate = t.interpolate({ inputRange: [0, 1], outputRange: ['0deg', `${spin}deg`] })
  const opacity = t.interpolate({ inputRange: [0, 0.05, 0.85, 1], outputRange: [0, 1, 1, 0] })
  return (
    <Animated.Text style={{ position: 'absolute', left: x, top: 0, fontSize: size, opacity,
                            transform: [{ translateY }, { translateX }, { rotate }] }}>
      {token}
    </Animated.Text>
  )
}

export function ChampionFanfare({ width = 393 }) {
  // Fixed at mount: re-rolling on each render would restart every piece.
  const pieces = useRef(Array.from({ length: PIECES }, (_, i) => ({
    token: TOKENS[i < 6 ? i % 3 : Math.floor(Math.random() * TOKENS.length)],
    x: Math.random() * width,
    delay: Math.floor(Math.random() * 2400),
    drift: (Math.random() - 0.5) * 160,
    spin: (Math.random() - 0.5) * 720,
    size: 18 + Math.floor(Math.random() * 18),
  }))).current
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {pieces.map((p, i) => <Piece key={i} {...p} />)}
    </View>
  )
}

/* ── A standout pick ──────────────────────────────────────────────────────
   The site's .cv-group--standout: a neon ring that spins through the
   spectrum four times while the chip shakes in and grows, then settles a
   little larger with a static neon edge. The ring is a sibling View whose
   border colour walks the spectrum; the shake is the site's keyframes. */
/* THE STANDOUT IS STATIC ON THE PHONE (owner, 2026-09-09): a neon edge, no
   shake, no spectrum walk. The site shakes the chip and walks the ring's
   border through the spectrum; here the colour walk had to run on the JS
   thread (a colour cannot take the native driver), so every standout chip
   repainted every frame for ten seconds after each mount — and the owner
   could feel it in the round scrub. The useStandoutShake/NeonRing names
   stay, for the chip that hosts them. */
const NEON_GREEN = '#39ff14'

/* No shake any more: the chip is not transformed. Kept as a hook so the
   host's transform stays a stable, empty list. */
export function useStandoutShake() {
  return EMPTY
}
const EMPTY = []

/* The neon ring: a static border and glow. */
export function NeonRing({ on, radius = 4 }) {
  if (!on) return null
  return (
    <View pointerEvents="none"
          style={[s.neon, { borderRadius: radius + 2, borderColor: NEON_GREEN, shadowColor: NEON_GREEN }]} />
  )
}

const s = StyleSheet.create({
  veil: { backgroundColor: '#ffffff', borderRadius: 6 },
  lifted: { zIndex: 5 },
  ring: {
    position: 'absolute', left: -3, right: -3, top: -3, bottom: -3,
    borderWidth: 3,
    shadowOffset: { width: 0, height: 0 }, shadowOpacity: 0.7, shadowRadius: 10,
  },
  neon: {
    position: 'absolute', left: -2, right: -2, top: -2, bottom: -2,
    borderWidth: 2,
    shadowOffset: { width: 0, height: 0 }, shadowOpacity: 0.6, shadowRadius: 6,
    backgroundColor: 'transparent',
  },
})
