/*
 * The brand's typefaces.
 *
 * Saira Condensed and Archivo are the website's display and body faces. Using
 * them is most of what makes the app read as the same product rather than a
 * React Native default — a native app in system San Francisco looks like every
 * other native app, which is fine until it is sitting next to a site with a
 * condensed scoreboard face.
 *
 * Only the weights actually used are loaded. Each is a real file shipped in the
 * binary, so an unused weight is dead bytes on every install.
 */

/* EACH FACE FROM ITS OWN PATH, never from the family index.
 *
 * `@expo-google-fonts/archivo`'s index re-exports EVERY weight and style the
 * family has, and each of those is a `require` of a TTF — so importing one
 * face by name registered all sixteen as bundle assets. Measured in the iOS
 * bundle before this change: 45 font files across three families, 11 MB, for
 * the nine faces the app draws with (owner, 2026-09-20 — keep Metro light).
 *
 * Each face also ships its own module, so this form pulls exactly what it
 * names. The paths are longer and that is the whole point: what is written
 * here is what ships.
 */
import { Archivo_400Regular } from '@expo-google-fonts/archivo/400Regular'
import { Archivo_400Regular_Italic } from '@expo-google-fonts/archivo/400Regular_Italic'
import { Archivo_500Medium } from '@expo-google-fonts/archivo/500Medium'
import { Archivo_700Bold } from '@expo-google-fonts/archivo/700Bold'
import { Kanit_300Light_Italic } from '@expo-google-fonts/kanit/300Light_Italic'
import { Kanit_900Black_Italic } from '@expo-google-fonts/kanit/900Black_Italic'
import { SairaCondensed_600SemiBold } from '@expo-google-fonts/saira-condensed/600SemiBold'
import { SairaCondensed_700Bold } from '@expo-google-fonts/saira-condensed/700Bold'
import { SairaCondensed_900Black } from '@expo-google-fonts/saira-condensed/900Black'

export const FONTS = {
  /* THE TIER BADGE, which used to be six PNGs (owner, 2026-09-20). A heavy
     italic for the tour's wordmark and a light one for the number — the
     contrast the artwork had and a single weight cannot give. Two files
     against the 22 KB of artwork they replace, and nothing to fetch or
     decode while a card is drawing. */
  Kanit_900Black_Italic,
  Kanit_300Light_Italic,
  SairaCondensed_600SemiBold,
  SairaCondensed_700Bold,
  SairaCondensed_900Black,     // the wordmark only — the site sets it at 900
  Archivo_400Regular,
  Archivo_400Regular_Italic,   // the wordmark's slogan, and nothing else
  Archivo_500Medium,
  Archivo_700Bold,
}
