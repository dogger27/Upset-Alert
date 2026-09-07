/*
 * A tournament bracket, as an icon.
 *
 * DRAWN FROM PLAIN VIEWS, not an SVG. Ionicons has no bracket glyph — the tab
 * wore `git-network`, a node tree, which is a different shape saying a
 * different thing — and react-native-svg is not installed here; adding it
 * would restart Metro for one icon. A bracket is entirely horizontal and
 * vertical bars, which is exactly the shape a View draws for free.
 *
 * Laid out on a 24x24 grid and scaled, so it stays true at any tab-bar size
 * and at any Dynamic Type setting the bar asks for.
 *
 *    ──┐
 *      ├──┐
 *    ──┘  │
 *         ├──
 *    ──┐  │
 *      ├──┘
 *    ──┘
 */
import { View } from 'react-native'

export function BracketIcon({ size = 22, color = '#fff' }) {
  const u = size / 24
  // Round to a whole pixel: a 1.7px bar renders blurred, and at icon scale
  // that reads as a rendering fault rather than a thin line.
  const w = Math.max(1.5, Math.round(2 * u))

  // Bars are centred on their grid line, so a coordinate means the same thing
  // whichever direction the bar runs.
  const H = (x, y, len) => ({
    position: 'absolute', left: x * u, top: y * u - w / 2,
    width: len * u, height: w, backgroundColor: color, borderRadius: w / 2,
  })
  const V = (x, y, len) => ({
    position: 'absolute', left: x * u - w / 2, top: y * u,
    width: w, height: len * u, backgroundColor: color, borderRadius: w / 2,
  })

  return (
    <View style={{ width: size, height: size }}>
      {/* Top pair, closed by a vertical: two players into one winner. */}
      <View style={H(1, 3, 7)} />
      <View style={H(1, 9, 7)} />
      <View style={V(8, 3, 6)} />
      {/* Bottom pair, the same. */}
      <View style={H(1, 15, 7)} />
      <View style={H(1, 21, 7)} />
      <View style={V(8, 15, 6)} />
      {/* Each pair's winner carried to the middle, and joined. */}
      <View style={H(8, 6, 8)} />
      <View style={H(8, 18, 8)} />
      <View style={V(16, 6, 12)} />
      {/* Out of the last vertical: the champion. */}
      <View style={H(16, 12, 7)} />
    </View>
  )
}
