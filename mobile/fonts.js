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

import {
  SairaCondensed_600SemiBold,
  SairaCondensed_700Bold,
  SairaCondensed_900Black,
} from '@expo-google-fonts/saira-condensed'
import {
  Kanit_300Light_Italic,
  Kanit_900Black_Italic,
} from '@expo-google-fonts/kanit'
import {
  Archivo_400Regular,
  Archivo_400Regular_Italic,
  Archivo_500Medium,
  Archivo_700Bold,
} from '@expo-google-fonts/archivo'

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
