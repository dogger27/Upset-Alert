import { useEffect, useState } from 'react'
import { useAuth } from '../store/auth'
import { ALL_NOTIFICATION_KEYS, pushKey } from '../constants/notifications'
import './PushPrompt.css'
import { lazyImport } from '../utils/chunk'

/*
 * Offers push to a signed-in phone that hasn't been asked yet.
 *
 * This is a SOFT ask: our own banner, with the browser's real permission prompt
 * fired only if they tap Enable. That indirection is the whole point. A native
 * "Deny" is close to permanent — the browser blocks the origin and the site can
 * never ask again; the user has to find it in browser or OS settings. Tapping
 * "Not now" here costs nothing and leaves the real prompt unspent.
 *
 * It cannot be automatic either way: Notification.requestPermission() is
 * rejected unless it comes from a user gesture, which is the same reason
 * ticking a Push box in settings enrols immediately instead of waiting for Save.
 */

// Burned when the banner is SHOWN, not when it is answered — the same rule as
// the install banner. Per browser rather than per account, because enrolment is
// per device: a phone and a laptop each need their own offer.
const SHOWN_KEY = 'ua-push-offered'
// Set by InstallPrompt. Read here so the two banners never stack.
const INSTALL_SHOWN_KEY = 'ua-install-offered'

const isMobile = () => /iPad|iPhone|iPod|Android/.test(navigator.userAgent)

const isStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches ||
  window.navigator.standalone === true

export default function PushPrompt() {
  const { user } = useAuth()
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!user) return
    if (!isMobile()) return
    if (localStorage.getItem(SHOWN_KEY)) return

    // On iOS the Push API only exists in an installed app, so an un-installed
    // iPhone has nothing to grant and the install banner is the right offer
    // instead. Android can grant from a tab, but if the install banner is about
    // to appear this visit, two stacked banners is worse than waiting — its key
    // is set the moment it shows, so the next visit is ours.
    if (!isStandalone() && !localStorage.getItem(INSTALL_SHOWN_KEY)) return

    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const push = await lazyImport(() => import('../api/push'))
        if (!push.isPushSupported()) return
        // 'denied' can never be re-asked from a page, and 'granted' means some
        // device already holds permission — neither is an offer worth making.
        if (typeof Notification !== 'undefined' && Notification.permission !== 'default') return

        // Already enrolled elsewhere on this account? Still ask, because
        // enrolment is per device and this one has none — but only if THIS
        // browser has no live subscription.
        const reg = await navigator.serviceWorker.getRegistration()
        const sub = reg && (await reg.pushManager.getSubscription())
        if (sub) return

        if (cancelled) return
        localStorage.setItem(SHOWN_KEY, '1')
        setVisible(true)
      } catch {
        // A capability probe that throws is not a reason to show anything.
      }
    }, 2200)

    return () => { cancelled = true; clearTimeout(t) }
  }, [user])

  const enable = async () => {
    setBusy(true)
    setNote('')
    try {
      const push = await lazyImport(() => import('../api/push'))
      await push.enablePush()

      // Permission alone delivers nothing: every type is opt-in, and push is a
      // separate key per type. Enrolling without switching anything on would
      // leave them granting permission and then receiving silence.
      //
      // Merged, never replaced — PUT /auth/me/notifications deletes the user's
      // whole set and re-inserts what it is given, so sending only the push
      // keys would wipe every email preference they have.
      const { default: client } = await import('../api/client')
      const { data } = await client.get('/auth/me/notifications')
      const merged = new Set(data.enabled_keys || [])
      ALL_NOTIFICATION_KEYS.forEach(k => merged.add(pushKey(k)))
      await client.put('/auth/me/notifications', { enabled_keys: [...merged] })

      setDone(true)
      setTimeout(() => setVisible(false), 2600)
    } catch (e) {
      const m = e?.message
      setNote(
        m === 'denied'
          ? 'Notifications are blocked for this site. You can re-allow them in your browser settings.'
          : m === 'not-configured'
          ? 'Push isn’t configured on the server yet.'
          : m === 'unsupported'
          ? 'This browser doesn’t support notifications.'
          : 'Couldn’t turn notifications on. You can try again from Notifications in your profile menu.'
      )
    } finally {
      setBusy(false)
    }
  }

  if (!visible) return null

  return (
    <div className="push-banner" role="dialog" aria-label="Turn on notifications">
      <img className="push-banner-icon" src="/favicon-192x192.png" alt="" />
      <div className="push-banner-text">
        <strong>{done ? 'Notifications are on' : 'Turn on notifications?'}</strong>
        <span>
          {done
            ? 'Change which ones you get any time under Notifications in your profile menu.'
            : note ||
              'Draws opening, players replaced, qualifiers, and how your picks did.'}
        </span>
      </div>
      {!done && (
        <>
          <button className="push-banner-cta" onClick={enable} disabled={busy}>
            {busy ? '…' : 'Enable'}
          </button>
          <button
            className="push-banner-x"
            onClick={() => setVisible(false)}
            aria-label="Not now"
          >
            ×
          </button>
        </>
      )}
    </div>
  )
}
