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

// In-app browsers (Facebook, Instagram, X) can't add to the Home Screen at all,
// so telling an iOS user to look for a Share option they don't have would just
// waste their time — they have to open in Safari first.
const isInAppBrowser = () =>
  /FBAN|FBAV|Instagram|Line\/|Twitter/.test(navigator.userAgent)

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
      ? [
          'Tap the ⋯ menu in this app’s browser bar.',
          'Choose “Open in browser” (Safari on iPhone, Chrome on Android).',
          'Then follow the steps there — this in-app browser can’t open or add apps.',
        ]
      : installed
      ? [
          'Tap the ⋮ menu in the top right.',
          'Choose “Open in Upset Alert”.',
          'Or just tap the Upset Alert icon on your home screen.',
        ]
      : os === 'ios'
      ? [
          // Where the button is, not just what it looks like. The old wording
          // named the icon and stopped, and the one report we have from a real
          // iPhone user was "can't find the share button" — it sits in Safari's
          // bottom toolbar, which hides itself as soon as you scroll.
          <>
            Tap the Share button <ShareIcon /> at the <strong>bottom</strong> of the
            screen. Don’t see it? Scroll up, or tap the very bottom once to bring
            the bar back.
          </>,
          <>Scroll down that list and tap <strong>“Add to Home Screen”</strong>.</>,
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
          <strong>{installed ? 'Open in app' : os === 'ios' ? 'Add to Home Screen' : 'Install app'}</strong>
          <span>
            {installed
              ? 'You already have Upset Alert installed.'
              : 'Full screen, and notifications when draws are released.'}
          </span>
        </div>
        <button className="install-banner-cta" onClick={onInstallClick}>
          {installed ? 'How' : os === 'ios' ? 'Show me' : 'Install'}
        </button>
        <button className="install-banner-x" onClick={dismiss} aria-label="Dismiss">×</button>
      </div>

      {showSteps && (
        <div className="install-steps-backdrop" onClick={() => setShowSteps(false)}>
          <div className="install-steps" onClick={(e) => e.stopPropagation()}>
            <h3>
              {isInAppBrowser()
                ? 'Open in your browser first'
                : installed
                ? 'Open the Upset Alert app'
                : os === 'ios'
                ? 'Add Upset Alert to your Home Screen'
                : 'Install on Android'}
            </h3>
            <ol>
              {steps.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
            {os === 'ios' && !isInAppBrowser() && (
              <>
                {/* Opened from Messages, WhatsApp, Gmail, LinkedIn and the rest,
                    iOS uses a built-in browser whose share sheet has no "Add to
                    Home Screen". Its user-agent is identical to Safari's, so it
                    cannot be detected the way the named social apps are — only
                    mentioned. This is the likeliest reason someone following the
                    steps exactly still finds nothing. */}
                <p className="install-steps-note">
                  Opened this from a text or email? Tap the compass icon to open it
                  in Safari first — built-in browsers can’t add to the Home Screen.
                </p>
                <p className="install-steps-note">
                  Already added it? Just open Upset Alert from your Home Screen —
                  iPhone can’t switch you there automatically.
                </p>
                <p className="install-steps-note">
                  Notifications on iPhone only work once the app is on your Home Screen —
                  Safari can’t send them from a tab.
                </p>
              </>
            )}
            <button className="install-steps-done" onClick={() => setShowSteps(false)}>Got it</button>
          </div>
        </div>
      )}
    </>
  )
}
