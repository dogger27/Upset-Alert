import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import clsx from 'clsx'
import { useAuth } from '../store/auth'
import './Navbar.css'

// Below this navbar width the primary nav links collapse into a hamburger menu.
const NAV_BREAKPOINT = 900

export default function Navbar() {
  const { user, logout, updateProfile } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [navCollapsed, setNavCollapsed] = useState(false)
  const [hamburgerOpen, setHamburgerOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [notifying, setNotifying] = useState(false)
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Notification panel state
  const [notifSelected, setNotifSelected] = useState(new Set())
  const [notifLeagues, setNotifLeagues] = useState([])
  const [notifLoading, setNotifLoading] = useState(false)
  const [notifSaving, setNotifSaving] = useState(false)
  const [notifError, setNotifError] = useState('')

  // Push lives outside notifSelected on purpose: enabling it must happen on the
  // click itself, because both iOS and Chrome reject a permission request that
  // isn't tied to a user gesture — deferring it to Save would fail silently.
  const [pushOn, setPushOn] = useState(false)
  const [pushBusy, setPushBusy] = useState(false)
  const [pushNote, setPushNote] = useState('')
  // Whether this browser could ever receive a push, as distinct from whether it
  // currently does. Null until checked, so the column isn't flashed and hidden.
  const [pushSupported, setPushSupported] = useState(null)
  const [pushDevices, setPushDevices] = useState(0)
  // Which capability is absent, so an "unavailable" report from a device I
  // can't inspect says WHY rather than just that.
  const [pushMissing, setPushMissing] = useState([])
  // The status lookup failed. Distinct from unsupported: the column stays.
  const [pushCheckFailed, setPushCheckFailed] = useState(false)

  const menuRef = useRef(null)
  const navRef = useRef(null)
  const hamburgerRef = useRef(null)

  // Collapse the primary nav links into a hamburger when the bar gets narrow.
  useEffect(() => {
    const el = navRef.current
    if (!el) return
    const measure = () => setNavCollapsed(el.clientWidth < NAV_BREAKPOINT)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Close the hamburger once there's room to show the links inline again.
  useEffect(() => { if (!navCollapsed) setHamburgerOpen(false) }, [navCollapsed])

  useEffect(() => {
    if (!hamburgerOpen) return
    const handler = (e) => {
      if (hamburgerRef.current && !hamburgerRef.current.contains(e.target)) setHamburgerOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [hamburgerOpen])

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
        setEditing(false)
        setNotifying(false)
        setError('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  const openEdit = () => {
    setUsername(user?.username ?? user?.display_name ?? '')
    setFullName(user?.full_name ?? '')
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setError('')
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setError('')
  }

  const openNotifications = async () => {
    setNotifying(true)
    setNotifError('')
    setNotifLoading(true)
    try {
      const { default: client } = await import('../api/client')
      const { data } = await client.get('/auth/me/notifications')
      const keys = new Set(data.enabled_keys)
      // Reconcile accounts saved before Draw Completion became conditional
      // (the old defaults set both), so what's stored matches what's shown.
      if (keys.has('round_standings')) keys.delete('tournament_end')
      setNotifSelected(keys)
    } catch {
      setNotifError('Failed to load preferences')
    } finally {
      setNotifLoading(false)
    }

    // "On" means this browser holds a live subscription AND the server still
    // has a row for it — either half alone would show a switch that lies.
    // Support is a capability question, answered synchronously and with no
    // network involved. It used to share a try/catch with the status lookup
    // below, so ANY failure there — a blip on /push/status, a service worker
    // call throwing — reported "push isn't available in this browser" and hid
    // the whole column, on devices that were already receiving pushes.
    let supported = false
    let missing = []
    try {
      const push = await import('../api/push')
      supported = push.isPushSupported()
      if (!supported) {
        if (!('serviceWorker' in navigator)) missing.push('service worker')
        if (!('PushManager' in window)) missing.push('push')
        if (!('Notification' in window)) missing.push('notifications')
      }
      setPushSupported(supported)
      setPushMissing(missing)
      if (!supported) {
        setPushOn(false)
        return
      }

      // Separate from the capability answer: this can fail without meaning
      // anything about what the browser can do, so it only ever clears the
      // "on" state — never the column.
      try {
        const reg = await navigator.serviceWorker.getRegistration()
        const sub = reg && (await reg.pushManager.getSubscription())
        const status = await push.getPushStatus()
        setPushDevices(status.device_count || 0)
        setPushOn(Boolean(sub) && status.device_count > 0)
        setPushCheckFailed(false)
      } catch {
        setPushOn(false)
        setPushCheckFailed(true)
      }
    } catch {
      // Only the module import itself failed; still not a capability verdict.
      setPushSupported(true)
      setPushOn(false)
      setPushCheckFailed(true)
    }
  }

  // Ticking any Push box has to do two separate things: record the preference
  // (saved with everything else on Save) and make sure THIS device can actually
  // receive. The second half must happen on the click, because iOS and Chrome
  // both reject a permission request that isn't tied to a user gesture — so it
  // cannot be deferred to Save like the checkbox state can.
  const togglePushFor = async (key) => {
    const pk = `push_${key}`
    // Enrolment comes first on a device that has none — before, and regardless
    // of, the tick state. The ticks are ACCOUNT preferences, so on a second
    // device they already render ticked from the first one; the old order read
    // that as "turning it off", unticked, and returned without ever
    // registering. A laptop could therefore never be enrolled at all: every
    // Push box was already ticked, so every click took the off path.
    if (!pushOn) {
      setPushNote('')
      setPushBusy(true)
      try {
        const push = await import('../api/push')
        if (!push.isPushSupported()) {
          setPushNote(
            push.needsInstall()
              ? 'On iPhone, add Upset Alert to your Home Screen first — Safari only allows notifications for installed apps.'
              : 'This browser does not support notifications.'
          )
          return
        }
        await push.enablePush()
        setPushOn(true)
        setPushDevices((n) => n + 1)
      } catch (e) {
        const m = e?.message
        setPushNote(
          m === 'denied'
            ? 'Notifications are blocked for this site. Re-allow them in your browser settings, then try again.'
            : m === 'not-configured'
            ? 'Push is not configured on the server yet.'
            : m === 'unsupported'
            ? 'This browser does not support notifications.'
            : 'Could not enable notifications on this device.'
        )
        return
      } finally {
        setPushBusy(false)
      }
      // Enrolling IS the whole intent of a click on an unregistered device.
      // The preference may already be on from another device, and unticking it
      // here would undo a setting the user never asked to change.
      if (!notifSelected.has(pk)) toggleNotif(pk)
      return
    }
    toggleNotif(pk)
  }

  // Proves the last hop — signing and subscribing can both be fine while
  // delivery to the handset still fails, and the alternative is discovering
  // that when a real draw releases.
  // Replays the most recent REAL notification of that type, so what lands is
  // what the next one will look like — a generic "test" only proves the pipe.
  const testPush = async (prefKey) => {
    setPushBusy(true)
    setPushNote('')
    try {
      const { sendTypedTestPush } = await import('../api/push')
      const { devices, delivered, title } = await sendTypedTestPush(prefKey)
      setPushNote(
        delivered === 0
          ? 'No device accepted it — the registration may have expired. Untick and re-tick a Push box to re-register.'
          : `Sent “${title}” to ${delivered} of ${devices} device(s).`
      )
    } catch (e) {
      setPushNote(e?.response?.data?.detail || 'Could not send the test notification.')
    } finally {
      setPushBusy(false)
    }
  }

  // Rows of the settings grid. Email and push are separate preference keys, so
  // a row can be on for one channel and off for the other.
  // Descriptions are kept to roughly one line at panel width: with a bold
  // label above each, a two-line description made every row three lines tall
  // and four rows filled the whole dropdown.
  // Two groups, because the rows answer two different questions. The first two
  // reach you whether or not you have entered anything; the rest only ever fire
  // about a draw you are already competing in, which is the single fact that
  // decides whether a row is worth switching on.
  const NOTIF_GROUPS = [
    {
      title: 'General',
      rows: [
        { key: 'draw_released', label: 'New draw released',
          desc: 'Once a week, when all draws are out' },
        { key: 'league_member_joined', label: 'New league member',
          desc: 'Someone joins a league you own' },
      ],
    },
    {
      title: "Draws I'm Competing In",
      rows: [
        { key: 'draw_changed', label: 'Draw change',
          desc: 'A player is replaced in a draw you entered' },
        { key: 'qualifiers_added', label: 'Qualifiers added',
          desc: 'Qualifying slots are filled, with their first matches' },
        { key: 'standout_pick', label: 'Standout pick',
          desc: 'You called a result most competitors missed' },
        { key: 'round_standings', label: 'Round completion',
          // Wrapped rather than referenced directly: this is built above
          // toggleRoundStandings' const declaration, so naming it here would
          // read it in the temporal dead zone and throw on every render.
          desc: 'After every round', onEmail: () => toggleRoundStandings() },
        { key: 'tournament_end', label: 'Draw completion',
          desc: 'Final standings only',
          // Round completion already reports every round, the Final included,
          // so while that is on this row is covered by it: shown ticked and
          // greyed rather than removed. Hiding it made the panel's rows move
          // under the finger that had just tapped the row above.
          coveredBy: 'round_standings' },
      ],
    },
  ]
  // Flat view for cross-row lookups (coveredBy), which do not care about groups.
  const NOTIF_ROWS = NOTIF_GROUPS.flatMap(g => g.rows)

  const toggleNotif = (key) => {
    setNotifSelected(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  // Round Completion already reports every round, the Final included, so Draw
  // Completion is only offered once rounds are switched off — and is turned on
  // at that moment, since it becomes the only way to hear a draw's result.
  // Both now arrive as the same weekly digest; tournament_end simply narrows it
  // to the Final round. Switching rounds back on clears it, so nobody holds two
  // preferences that would put them in the same batch twice.
  const toggleRoundStandings = () => {
    setNotifSelected(prev => {
      const next = new Set(prev)
      if (next.has('round_standings')) {
        next.delete('round_standings')
        next.add('tournament_end')
      } else {
        next.add('round_standings')
        next.delete('tournament_end')
      }
      return next
    })
  }

  const saveNotif = async () => {
    setNotifSaving(true)
    setNotifError('')
    try {
      const { default: client } = await import('../api/client')
      await client.put('/auth/me/notifications', { enabled_keys: [...notifSelected] })
      setNotifying(false)
    } catch {
      setNotifError('Failed to save')
    } finally {
      setNotifSaving(false)
    }
  }

  const cancelNotif = () => {
    setNotifying(false)
    setNotifError('')
  }

  const saveEdit = async () => {
    const changingPassword = currentPassword || newPassword || confirmPassword
    if (changingPassword) {
      if (!currentPassword) { setError('Enter your current password'); return }
      if (newPassword.length < 8) { setError('New password must be at least 8 characters'); return }
      if (newPassword !== confirmPassword) { setError('Passwords do not match'); return }
    }
    setSaving(true)
    setError('')
    try {
      await updateProfile({ username: username.trim() || undefined, full_name: fullName.trim() || undefined })
      if (changingPassword) {
        const { default: client } = await import('../api/client')
        await client.patch('/auth/me/password', { current_password: currentPassword, new_password: newPassword })
      }
      setEditing(false)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleLogout = () => {
    setMenuOpen(false)
    logout()
    navigate('/')
  }

  const isActive = (path) => path === '/' ? location.pathname === '/' : location.pathname.startsWith(path)

  const onTournament = /^\/tournaments\/[^/]+/.test(location.pathname)
  const NAV_ITEMS = [
    { to: '/', label: 'Dashboard', match: '/' },
    { to: '/leagues', label: 'Leagues', match: '/leagues' },
    { to: '/rules', label: 'Rules', match: '/rules' },
    { to: '/hall-of-fame', label: 'Hall of Fame', match: '/hall-of-fame' },
    { to: '/about', label: 'About', match: '/about' },
  ]

  return (
    <nav className="navbar" ref={navRef}>
      <div className="navbar-left">
        {navCollapsed && (
          <div className="navbar-hamburger" ref={hamburgerRef}>
            <button
              className="hamburger-btn"
              onClick={() => setHamburgerOpen(o => !o)}
              aria-label="Menu"
              aria-expanded={hamburgerOpen}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            {hamburgerOpen && (
              <div className="hamburger-dropdown">
                {onTournament && (
                  <span className="hamburger-item hamburger-item--active">Draw</span>
                )}
                {NAV_ITEMS.map(n => (
                  <Link
                    key={n.to}
                    to={n.to}
                    className={clsx('hamburger-item', { 'hamburger-item--active': isActive(n.match) })}
                    onClick={() => setHamburgerOpen(false)}
                  >
                    {n.label}
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <Link to="/" className="navbar-brand">
        <div className="navbar-brand-top">
          <span className="navbar-brand-dot" />
          <span className="navbar-brand-text">
            <span className="navbar-brand-upset">Upset</span>{' '}
            <span className="navbar-brand-alert">Alert</span><span className="navbar-brand-exclaim">!</span>
          </span>
        </div>
        <span className="navbar-brand-slogan">Your Wildest Fantasy Tennis</span>
      </Link>
      <div className="navbar-links">
        {!navCollapsed && (
          <>
            {onTournament && (
              <span className="navbar-label navbar-active">Draw</span>
            )}
            {NAV_ITEMS.map(n => (
              <Link key={n.to} to={n.to} className={isActive(n.match) ? 'navbar-active' : ''}>{n.label}</Link>
            ))}
          </>
        )}
        {user ? (
          <>
            {user.is_admin && <Link to="/admin" className="navbar-admin-btn" title="Admin">A</Link>}
            <div className="navbar-profile" ref={menuRef}>
              <button
                className="navbar-user"
                onClick={() => { setMenuOpen(s => !s); setEditing(false); setError('') }}
                aria-expanded={menuOpen}
              >
                <svg className="navbar-user-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <circle cx="12" cy="8" r="4" />
                  <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                </svg>
              </button>
              {menuOpen && (
                <div className="profile-dropdown">
                  {!editing && !notifying ? (
                    <>
                      <div className="profile-dropdown-header">
                        <span className="profile-dropdown-name">{user.display_name}</span>
                        <span className="profile-dropdown-email">{user.email}</span>
                      </div>
                      <div className="profile-dropdown-divider" />
                      <button className="profile-dropdown-item" onClick={openEdit}>
                        Edit profile
                      </button>
                      <Link
                        className="profile-dropdown-item"
                        to={`/draw-history?user=${user.id}`}
                        onClick={() => setMenuOpen(false)}
                      >
                        My Draw History
                      </Link>
                      <button className="profile-dropdown-item" onClick={openNotifications}>
                        Notifications
                      </button>
                      <div className="profile-dropdown-divider" />
                      <button className="profile-dropdown-item profile-dropdown-item--danger" onClick={handleLogout}>
                        Log out
                      </button>
                    </>
                  ) : notifying ? (
                    <div className="notif-form">
                      <div className="notif-form-header">
                        <button className="notif-back-btn" onClick={cancelNotif}>←</button>
                        <span className="profile-edit-title">Notifications</span>
                      </div>

                      {notifLoading ? (
                        <p className="notif-loading">Loading…</p>
                      ) : (
                        <>
                          <table className={`notif-grid${pushBusy ? ' is-busy' : ''}`}>
                            <thead>
                              <tr>
                                <th className="notif-grid-type">Notification</th>
                                <th>Email</th>
                                {pushSupported !== false && <th className="notif-grid-push">Push</th>}
                              </tr>
                            </thead>
                            <tbody>
                              {NOTIF_GROUPS.flatMap(g => [
                                <tr key={`h-${g.title}`} className="notif-group-row">
                                  <td colSpan={pushSupported !== false ? 3 : 2}>{g.title}</td>
                                </tr>,
                                ...g.rows.map(r => {
                                // Each channel locks independently: round-completion
                                // email covers draw-completion email, and the same
                                // for push, but one being on says nothing about the
                                // other. Locked shows ticked because the recipient
                                // does get that notification — via the row above.
                                const emailLocked = !!r.coveredBy && notifSelected.has(r.coveredBy)
                                const pushLocked = !!r.coveredBy && notifSelected.has(`push_${r.coveredBy}`)
                                const covered = NOTIF_ROWS.find(x => x.key === r.coveredBy)
                                const why = covered ? `Included in ${covered.label}` : undefined
                                return (
                                <tr key={r.key}>
                                  <td className="notif-grid-type">
                                    <span className="notif-grid-label">{r.label}</span>
                                    <span className="notif-grid-desc">{r.desc}</span>
                                  </td>
                                  <td>
                                    <input
                                      type="checkbox"
                                      aria-label={`${r.label} email`}
                                      title={emailLocked ? why : undefined}
                                      disabled={emailLocked}
                                      checked={emailLocked || notifSelected.has(r.key)}
                                      onChange={r.onEmail || (() => toggleNotif(r.key))}
                                    />
                                  </td>
                                  {pushSupported !== false && (
                                    <td className="notif-grid-push">
                                      <span className="notif-push-cell">
                                        <input
                                          type="checkbox"
                                          aria-label={`${r.label} push`}
                                          title={pushLocked ? why : undefined}
                                          disabled={pushBusy || pushLocked}
                                          checked={pushLocked || notifSelected.has(`push_${r.key}`)}
                                          onChange={() => togglePushFor(r.key)}
                                        />
                                        {/* Only offered once this device can actually
                                            receive — otherwise it's a button whose only
                                            outcome is an error. */}
                                        {pushOn && (
                                          <button
                                            type="button"
                                            className="notif-test-icon"
                                            disabled={pushBusy}
                                            aria-label={`Send a test ${r.label} notification`}
                                            title={`Send a test ${r.label} notification`}
                                            onClick={() => testPush(r.key)}
                                          >
                                            <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                                              <path d="M1.5 7.6 14 2 8.9 14.3l-1.8-4.4-4.4-1.8Z"
                                                    fill="none" stroke="currentColor"
                                                    strokeWidth="1.4" strokeLinejoin="round" />
                                            </svg>
                                          </button>
                                        )}
                                      </span>
                                    </td>
                                  )}
                                </tr>
                                )
                              }),
                              ])}
                            </tbody>
                          </table>
                          <p className={`notif-device-state${pushOn ? ' is-on' : ''}`}>
                            {pushSupported === false
                              ? `Push isn’t available in this browser${pushMissing.length ? ` (no ${pushMissing.join(', ')})` : ''} — the ticks above still control your other devices.`
                              : pushCheckFailed
                              ? 'Couldn’t check this device just now. Reopen this panel, or tick a Push box to set it up.'
                              : pushOn
                              ? pushDevices > 1
                                ? `Notifications are on for this device (${pushDevices} devices registered).`
                                : 'Notifications are on for this device.'
                              : 'This device isn’t set up yet — tick a Push box to turn it on here. The ticks show what your account receives, not this device.'}
                          </p>
                          {pushNote && <p className="notif-push-note">{pushNote}</p>}

                          {notifError && <p className="profile-edit-error" style={{ padding: '0 1rem' }}>{notifError}</p>}
                          {/* Sticky to the panel's bottom edge — see .notif-actions.
                              The error sits above it deliberately: pinned, it would
                              eat the room the buttons need on a short screen. */}
                          <div className="profile-edit-actions notif-actions">
                            <button className="btn-secondary profile-edit-btn" onClick={cancelNotif} disabled={notifSaving}>
                              Cancel
                            </button>
                            <button className="btn-primary profile-edit-btn" onClick={saveNotif} disabled={notifSaving}>
                              {notifSaving ? 'Saving…' : 'Save'}
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  ) : (
                    <div className="profile-edit-form">
                      <p className="profile-edit-title">Edit profile</p>
                      <label className="profile-edit-label">User Name</label>
                      <input
                        className="profile-edit-input"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        placeholder="Username"
                        autoFocus
                      />
                      <label className="profile-edit-label">Full Name</label>
                      <input
                        className="profile-edit-input"
                        value={fullName}
                        onChange={e => setFullName(e.target.value)}
                        placeholder="Full name"
                      />
                      <div className="profile-dropdown-divider" style={{ margin: '0.75rem 0 0.5rem' }} />
                      <p className="profile-edit-label" style={{ fontWeight: 700, marginBottom: '0.5rem' }}>Change Password</p>
                      <label className="profile-edit-label">Current Password</label>
                      <input
                        className="profile-edit-input"
                        type="password"
                        value={currentPassword}
                        onChange={e => setCurrentPassword(e.target.value)}
                        placeholder="Current password"
                        autoComplete="current-password"
                      />
                      <label className="profile-edit-label">New Password</label>
                      <input
                        className="profile-edit-input"
                        type="password"
                        value={newPassword}
                        onChange={e => setNewPassword(e.target.value)}
                        placeholder="New password (min 8 chars)"
                        autoComplete="new-password"
                      />
                      <label className="profile-edit-label">Confirm New Password</label>
                      <input
                        className="profile-edit-input"
                        type="password"
                        value={confirmPassword}
                        onChange={e => setConfirmPassword(e.target.value)}
                        placeholder="Confirm new password"
                        autoComplete="new-password"
                      />
                      {error && <p className="profile-edit-error">{error}</p>}
                      <div className="profile-edit-actions">
                        <button className="btn-secondary profile-edit-btn" onClick={cancelEdit} disabled={saving}>
                          Cancel
                        </button>
                        <button className="btn-primary profile-edit-btn" onClick={saveEdit} disabled={saving}>
                          {saving ? 'Saving…' : 'Save'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        ) : null}
      </div>
    </nav>
  )
}
