import { useEffect, useState } from 'react'
import './InstallPrompt.css'

/*
 * Prompts a mobile visitor browsing in a tab to install the web app.
 *
 * Shown only when all three are true: it's a phone, it isn't already running
 * installed, and the banner hasn't been dismissed before. Desktop is excluded
 * because the payoff there is small and the interruption isn't.
 *
 * Android gets a real one-tap install when Chrome offers it. Chrome fires
 * beforeinstallprompt only when the site meets its prompt criteria — which
 * still include a service worker with a non-trivial fetch handler, and ours is
 * deliberately fetch-less so it can never serve stale assets. So the event
 * usually will NOT fire, and the instructions are the real path rather than a
 * fallback. It's still captured when offered, because a one-tap install beats
 * any instructions.
 */

// Marked the first time the banner is SHOWN, not when it's dismissed, so it
// appears exactly once and never nags. Per browser rather than per account,
// which is the right unit anyway: installing is a per-device act, so a phone
// and a laptop each need their own offer, and a signed-out visitor still gets
// one.
const SHOWN_KEY = 'ua-install-offered'

const isStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches ||
  window.navigator.standalone === true

/*
 * Already installed, seen from a browser tab.
 *
 * getInstalledRelatedApps is the only way to ask, it needs the manifest to list
 * itself under related_applications, and it exists on Chromium/Android only.
 * iOS has no equivalent — Safari cannot tell you whether the same site is
 * sitting on the Home Screen — so there the honest answer is "don't know", and
 * we fall back to offering the install.
 */
const isAlreadyInstalled = async () => {
  if (!navigator.getInstalledRelatedApps) return false
  try {
    const apps = await navigator.getInstalledRelatedApps()
    return apps.some((a) => a.platform === 'webapp')
  } catch {
    return false
  }
}

const platform = () => {
  const ua = navigator.userAgent
  if (/iPad|iPhone|iPod/.test(ua)) return 'ios'
  if (/Android/.test(ua)) return 'android'
  return 'other'
}

/*
 * Which browser, on iOS — because the taps genuinely differ and the old single
 * set of steps was wrong in both.
 *
 * Every iOS browser is WebKit underneath, so the engine tells you nothing; only
 * the vendor token does. Chrome puts Share in the address bar at the TOP.
 * Safari has no Share button in its bar at all any more — it moved inside the
 * ••• menu at the bottom, which is why "tap the Share button at the bottom of
 * the screen" sent people looking for something that is not there.
 *
 * Firefox and Edge fall through to the Safari steps: they are also ⋯-then-Share
 * and their menus are close enough to follow, which beats naming a browser we
 * have no screenshot of.
 */
const iosBrowser = () => (/CriOS/.test(navigator.userAgent) ? 'chrome' : 'safari')

/* A screenshot of the actual tap, with the button ringed.
 *
 * Worth the bytes: the alternative is prose describing where a button is, and
 * we already know from a real report that prose was not enough — the reader was
 * looking at a bar that does not contain what the sentence named. A picture of
 * their own screen is checkable at a glance.
 * Lazy, so the four images cost nothing until the sheet is opened. */
const Shot = ({ src, alt }) => (
  <img className="install-shot" src={src} alt={alt} loading="lazy" decoding="async" />
)

/*
 * In-app browsers cannot add to the Home Screen: they are WKWebViews, and "Add
 * to Home Screen" is a Safari-only action, so their share sheet does not offer
 * it. Sending someone there to hunt for it wastes their time and ends with them
 * concluding the site is broken.
 *
 * This list is a net, not a diagnosis. Each entry costs nothing when the app in
 * question hands links to the real browser instead — the branch simply never
 * fires, because it only matches a user-agent that names the app. Apps using
 * SFSafariViewController (iOS Messages and Mail among them) are invisible here
 * for the same reason: their user-agent is byte-identical to Safari's while
 * still lacking Add to Home Screen, so they can only be mentioned in the steps.
 *
 * So this is worth having, but it is NOT the thing to lean on. The instructions
 * for plain Safari have to be good enough on their own, because that is where
 * most people are and where we cannot tell that they are stuck.
 */
const IN_APP_BROWSERS =
  /WhatsApp|FBAN|FBAV|FB_IAB|Messenger|Instagram|Line\/|Twitter|LinkedInApp|Snapchat|BytedanceWebview|musical_ly|TikTok|Discord|Slack|Pinterest|Reddit/i

const isInAppBrowser = () => IN_APP_BROWSERS.test(navigator.userAgent)

// iOS share glyph: a box with an arrow leaving the top. Shown inline in the
// steps because "the square with an arrow pointing up" is a description someone
// has to translate before they can look for it.
const ShareIcon = () => (
  <svg className="install-inline-icon" viewBox="0 0 24 24" width="15" height="15"
       fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 15V3" />
    <polyline points="8,7 12,3 16,7" />
    <path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" />
  </svg>
)

// Named in the steps so the sentence matches the app the reader is holding —
// "WhatsApp's own browser" lands where "this in-app browser" does not.
const appName = () => {
  const ua = navigator.userAgent
  for (const [re, name] of [
    [/WhatsApp/i, 'WhatsApp'], [/Instagram/i, 'Instagram'],
    [/Messenger|FB_IAB|FBAN|FBAV/i, 'Facebook'], [/LinkedInApp/i, 'LinkedIn'],
    [/Snapchat/i, 'Snapchat'], [/TikTok|BytedanceWebview|musical_ly/i, 'TikTok'],
    [/Discord/i, 'Discord'], [/Slack/i, 'Slack'], [/Reddit/i, 'Reddit'],
    [/Pinterest/i, 'Pinterest'], [/Twitter/i, 'X'], [/Line\//i, 'LINE'],
  ]) if (re.test(ua)) return name
  return 'this app'
}

export default function InstallPrompt() {
  const [visible, setVisible] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const [deferred, setDeferred] = useState(null)
  // Android/Chromium can tell us; iOS never can, so there it stays false and
  // the sheet covers both possibilities in one set of steps instead.
  const [installed, setInstalled] = useState(false)
  const os = platform()

  useEffect(() => {
    if (os === 'other' || isStandalone()) return
    if (localStorage.getItem(SHOWN_KEY)) return

    const onBeforeInstall = (e) => {
      e.preventDefault()
      setDeferred(e)
    }
    window.addEventListener('beforeinstallprompt', onBeforeInstall)

    // If they install while the tab is open, the offer is moot.
    const onInstalled = () => { setVisible(false); setShowSteps(false) }
    window.addEventListener('appinstalled', onInstalled)

    // Short delay so the banner doesn't race the first paint — arriving on a
    // half-rendered page reads as an ad rather than an offer. The install check
    // rides along inside it.
    let cancelled = false
    const t = setTimeout(async () => {
      // Shown whether or not the app is installed: for someone who has it the
      // banner is a way back into it, and for someone who doesn't it's the
      // offer. Only the sheet behind the button differs.
      const inst = await isAlreadyInstalled()
      if (cancelled) return
      setInstalled(inst)
      // Burn the one offer at the moment it appears. Waiting for a dismissal
      // would re-show on every visit to anyone who just scrolls past it, which
      // is the behaviour "only once" exists to prevent.
      localStorage.setItem(SHOWN_KEY, '1')
      setVisible(true)
    }, 1500)

    return () => {
      cancelled = true
      clearTimeout(t)
      window.removeEventListener('beforeinstallprompt', onBeforeInstall)
      window.removeEventListener('appinstalled', onInstalled)
    }
  }, [os])

  const dismiss = () => {
    setVisible(false)
    setShowSteps(false)
  }

  const onInstallClick = async () => {
    // Only a not-yet-installed Android Chrome ever hands us this, and it's the
    // one path that can finish the job in a single tap.
    if (!installed && deferred) {
      deferred.prompt()
      const { outcome } = await deferred.userChoice
      setDeferred(null)
      if (outcome === 'accepted') return dismiss()
      return
    }
    setShowSteps(true)
  }

  if (!visible) return null

  /*
   * There is no web API that launches an installed PWA from a browser tab —
   * on any platform. Chrome exposes it as a user-driven menu item in its own
   * UI, and Android's link capturing handles navigations arriving from OTHER
   * apps, but a page cannot hand itself over. So "open the app" is directions,
   * not an action, and saying so beats a button that appears to do nothing.
   */
  const steps =
    isInAppBrowser()
      ? os === 'ios'
        ? [
            <>This is {appName()}’s own browser, and it can’t add apps to your
            Home Screen — only Safari can.</>,
            <>Tap the <ShareIcon /> or <strong>⋯</strong> button (usually
            bottom-right), then choose <strong>“Open in Safari”</strong>.</>,
            <>Once Safari opens, come back here and this tip will show you the
            two taps to add it.</>,
          ]
        : [
            'Tap the ⋯ menu in this app’s browser bar.',
            'Choose “Open in browser” (Chrome).',
            'Then follow the steps there — this in-app browser can’t add apps.',
          ]
      : installed
      ? [
          'Tap the ⋮ menu in the top right.',
          'Choose “Open in Upset Alert”.',
          'Or just tap the Upset Alert icon on your home screen.',
        ]
      : os === 'ios'
      ? iosBrowser() === 'chrome'
        ? [
            <>
              Tap the Share button <ShareIcon /> inside the address bar, at the
              <strong> top</strong> of the screen.
              <Shot src="/install/chrome-share.jpg"
                    alt="Chrome's address bar, with the Share button at its right end ringed" />
            </>,
            <>
              Scroll down that list and tap <strong>“Add to Home Screen”</strong>.
              <Shot src="/install/add-to-home.jpg"
                    alt="The share sheet scrolled down, with Add to Home Screen ringed" />
            </>,
            <>Tap <strong>“Add”</strong>, top right. Upset Alert is now an icon on your
            Home Screen — open it from there.</>,
          ]
        : [
            // Safari has no Share button in its bar any more. The old steps said
            // "the Share button at the bottom of the screen", and the one report
            // we have from a real iPhone user was "can't find the share button"
            // — because it is not there. It lives inside the ••• menu now.
            <>
              Tap the <strong>•••</strong> button at the <strong>bottom</strong> of
              the screen. Don’t see the bar? Scroll up, or tap the very bottom once
              to bring it back.
              <Shot src="/install/safari-more.jpg"
                    alt="Safari's bottom bar, with the ••• button at its right end ringed" />
            </>,
            <>
              Tap <strong>“Share”</strong> at the top of that menu.
              <Shot src="/install/safari-share.jpg"
                    alt="Safari's menu, with Share at the top ringed" />
            </>,
            <>
              Scroll down that list and tap <strong>“Add to Home Screen”</strong>.
              <Shot src="/install/add-to-home.jpg"
                    alt="The share sheet scrolled down, with Add to Home Screen ringed" />
            </>,
            <>Tap <strong>“Add”</strong>, top right. Upset Alert is now an icon on your
            Home Screen — open it from there.</>,
          ]
      : [
          'Tap the ⋮ menu in the top right.',
          'Tap “Install app” (some phones say “Add to Home screen”).',
          'Tap “Install” to confirm.',
        ]

  return (
    <>
      <div className="install-banner" role="dialog" aria-label="Open Upset Alert in the app">
        <img className="install-banner-icon" src="/favicon-192x192.png" alt="" />
        <div className="install-banner-text">
          {/* "Open in app" with a button saying "Open" promises an app that is
              already there. iPhone can never tell us whether it is
              (getInstalledRelatedApps is Chromium-only), so iOS always got that
              wording — and a real user read it as "download your app", then went
              looking for a download that does not exist. On iOS the honest offer
              is to ADD it; only Android can claim to open one. */}
          <strong>
            {isInAppBrowser() ? 'Open in your browser'
              : installed ? 'Open in app'
              : os === 'ios' ? 'Add to Home Screen'
              : 'Install app'}
          </strong>
          <span>
            {installed
              ? 'You already have Upset Alert installed.'
              : 'Full screen, and notifications when draws are released.'}
          </span>
        </div>
        <button className="install-banner-cta" onClick={onInstallClick}>
          {isInAppBrowser() || installed ? 'How' : os === 'ios' ? 'Show me' : 'Install'}
        </button>
        <button className="install-banner-x" onClick={dismiss} aria-label="Dismiss">×</button>
      </div>

      {showSteps && (
        <div className="install-steps-backdrop" onClick={() => setShowSteps(false)}>
          <div className="install-steps" onClick={(e) => e.stopPropagation()}>
            <h3>
              {isInAppBrowser()
                ? (os === 'ios' ? 'Open this in Safari first' : 'Open in your browser first')
                : installed
                ? 'Open the Upset Alert app'
                : os === 'ios'
                ? 'Add Upset Alert to your Home Screen'
                : 'Install on Android'}
            </h3>
            <ol>
              {steps.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
            {/* The three amber caveats that used to sit here are gone — the
                built-in-browser warning, the already-installed note and the
                notifications one. They were written when the steps were prose
                and covered every way prose could be misread; now each step
                shows the button it names, so the reader either finds it or is
                somewhere the pictures plainly do not match, which is the same
                information without three paragraphs of hedging under it. */}
            <button className="install-steps-done" onClick={() => setShowSteps(false)}>Got it</button>
          </div>
        </div>
      )}
    </>
  )
}
