/*
 * Metro, kept light (owner, 2026-09-20: "as fast and light weight as
 * possible. Offload whatever we don't need").
 *
 * The app had no config at all, so it ran Expo's defaults: every file under
 * the project and every file under node_modules in the resolver's view, and
 * a bundle that evaluates every module it contains at startup. Three changes,
 * each one a thing the app genuinely does not need.
 *
 * WHAT IS NOT HERE, and why. There is no custom transformer, no alias table
 * and no source-extension list: those change how modules resolve, which is
 * how a Metro config becomes the thing that breaks a build nobody can
 * explain. Everything below either narrows what Metro looks at or changes
 * when the bundle evaluates code.
 */
const fs = require('node:fs')
const path = require('node:path')
const { getDefaultConfig } = require('expo/metro-config')

const config = getDefaultConfig(__dirname)

/* 1. NO INLINE REQUIRES — TRIED, MEASURED, REVERTED.
 *
 * Deferring every module's evaluation to its first use is the documented
 * lever on React Native start-up, and this app looked like a good candidate:
 * expo-router pulls every route, @expo/vector-icons its glyph maps. It also
 * red-boxed the app on first render:
 *
 *   [Worklets] createSerializableObject should never be called in JSWorklets
 *
 * react-native-worklets has to install its runtime before anything creates a
 * worklet, and lazy evaluation puts those two in the wrong order. The draw's
 * swipe, the round scrub and the score animations are all Reanimated, so
 * this is not a corner of the app that could be worked around.
 *
 * Left here as a note rather than deleted, so the next person to reach for
 * it knows it was tried and what it cost. The two changes below are the ones
 * that survived, and both are about what Metro CARRIES rather than when it
 * evaluates.
 */

/* 2. NINE FONT FILES, NOT FORTY-FIVE.
 *
 * @expo-google-fonts ships every weight and style of a family: 45 TTFs and
 * 11 MB across the three families this app uses nine faces of. Metro will not
 * BUNDLE what nothing requires, but the resolver still carries them, and a
 * stray import of the wrong weight is a 100 KB mistake that nothing catches.
 * Blocking every face the app does not load makes that import fail loudly
 * instead.
 *
 * KEEP THIS IN STEP WITH fonts.js. A face added there and not here does not
 * resolve at all, which is a red box on first render rather than a silent
 * fallback — the right direction for a mistake to fail in.
 */
const FACES = [
  'Archivo_400Regular',
  'Archivo_400Regular_Italic',
  'Archivo_500Medium',
  'Archivo_700Bold',
  'SairaCondensed_600SemiBold',
  'SairaCondensed_700Bold',
  'SairaCondensed_900Black',
  'Kanit_900Black_Italic',
  'Kanit_300Light_Italic',
]
/* PER FAMILY, not one flat set of directory names. A face's directory is its
   name without the family prefix — "Kanit_900Black_Italic" lives in
   "900Black_Italic" — and those names repeat across families: keeping Saira
   Condensed's "900Black" in a flat set kept Kanit's and Archivo's too, which
   is three font files nothing loads. The prefix names the package:
   SairaCondensed -> saira-condensed. */
const KEEP = new Map()
for (const face of FACES) {
  const [, prefix, dir] = face.match(/^([A-Za-z]+?)_(.+)$/)
  const family = prefix.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase()
  if (!KEEP.has(family)) KEEP.set(family, new Set())
  KEEP.get(family).add(dir)
}

/* Enumerated rather than expressed as one clever pattern. A blockList regex
   built by concatenating raw and cooked template parts is how the first
   attempt at this shipped an INVALID character class — it threw at require
   time, which was lucky; a subtly wrong pattern would have blocked a face
   the app loads. Listing the directories that exist is dull, exact, and
   prints a number this file can be checked against. */
const FONT_ROOT = path.join(__dirname, 'node_modules', '@expo-google-fonts')
const WEIGHT_DIR = /^\d{3}[A-Za-z]/          // "900Black_Italic", not "package.json"
const unused = []
if (fs.existsSync(FONT_ROOT)) {
  for (const family of fs.readdirSync(FONT_ROOT)) {
    const dir = path.join(FONT_ROOT, family)
    if (!fs.statSync(dir).isDirectory()) continue
    for (const face of fs.readdirSync(dir)) {
      const keep = KEEP.get(family)
      if (WEIGHT_DIR.test(face) && !(keep && keep.has(face))) unused.push(path.join(dir, face))
    }
  }
}
const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
config.resolver.blockList = [
  ...(Array.isArray(config.resolver.blockList)
    ? config.resolver.blockList
    : config.resolver.blockList ? [config.resolver.blockList] : []),
  ...(unused.length ? [new RegExp(`^(?:${unused.map(escape).join('|')})[/\\\\]`)] : []),
]
if (process.env.METRO_REPORT) {
  console.log(`metro.config: ${FACES.length} font faces kept, ${unused.length} blocked`)
}

/* 3. DO NOT WATCH THE ARTWORK ARCHIVE.
 *
 * art/ holds the tours' print-resolution downloads — 1.3 MB the clients never
 * load, kept as the generators' input. It sits outside the project root, so
 * Metro would only reach it through a watchFolder; this states plainly that
 * it is not one, which is documentation as much as configuration.
 */
config.watchFolders = [__dirname]

module.exports = config
