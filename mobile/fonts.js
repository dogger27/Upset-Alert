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
} from '@expo-google-fonts/saira-condensed'
import {
  Archivo_400Regular,
  Archivo_500Medium,
  Archivo_700Bold,
} from '@expo-google-fonts/archivo'

export const FONTS = {
  SairaCondensed_600SemiBold,
  SairaCondensed_700Bold,
  Archivo_400Regular,
  Archivo_500Medium,
  Archivo_700Bold,
}
