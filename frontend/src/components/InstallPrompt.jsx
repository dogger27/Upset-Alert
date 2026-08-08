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

export default function InstallPrompt() {
  const [visible, setVisible] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const [deferred, setDeferred] = useState(null)
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
      if (await isAlreadyInstalled()) return   // has the app; don't pester
      if (cancelled) return
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
    if (deferred) {
      deferred.prompt()
      const { outcome } = await deferred.userChoice
      setDeferred(null)
      if (outcome === 'accepted') return dismiss()
      return
    }
    setShowSteps(true)
  }

  if (!visible) return null

  const steps =
    isInAppBrowser()
      ? [
          'Tap the ⋯ menu in this app’s browser bar.',
          'Choose “Open in browser” (Safari on iPhone, Chrome on Android).',
          'Then follow the install steps there — this in-app browser can’t add to your Home Screen.',
        ]
      : os === 'ios'
      ? [
          'Tap the Share button — the square with an arrow pointing up.',
          'Scroll down the list and tap “Add to Home Screen”.',
          'Tap “Add” in the top right.',
        ]
      : [
          'Tap the ⋮ menu in the top right.',
          'Tap “Install app” (some phones say “Add to Home screen”).',
          'Tap “Install” to confirm.',
        ]

  return (
    <>
      <div className="install-banner" role="dialog" aria-label="Install Upset Alert">
        <img className="install-banner-icon" src="/favicon-192x192.png" alt="" />
        <div className="install-banner-text">
          <strong>Install Upset Alert</strong>
          <span>Full screen, and notifications when draws are released.</span>
        </div>
        <button className="install-banner-cta" onClick={onInstallClick}>Install</button>
        <button className="install-banner-x" onClick={dismiss} aria-label="Dismiss">×</button>
      </div>

      {showSteps && (
        <div className="install-steps-backdrop" onClick={() => setShowSteps(false)}>
          <div className="install-steps" onClick={(e) => e.stopPropagation()}>
            <h3>
              {isInAppBrowser()
                ? 'Open in your browser first'
                : os === 'ios'
                ? 'Add to your iPhone Home Screen'
                : 'Install on Android'}
            </h3>
            <ol>
              {steps.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
            {os === 'ios' && !isInAppBrowser() && (
              <p className="install-steps-note">
                Notifications on iPhone only work once the app is on your Home Screen —
                Safari can’t send them from a tab.
              </p>
            )}
            <button className="install-steps-done" onClick={() => setShowSteps(false)}>Got it</button>
          </div>
        </div>
      )}
    </>
  )
}
