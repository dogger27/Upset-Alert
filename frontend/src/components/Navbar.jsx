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
    try {
      const { isPushSupported, getPushStatus } = await import('../api/push')
      if (!isPushSupported()) return setPushOn(false)
      const reg = await navigator.serviceWorker.getRegistration()
      const sub = reg && (await reg.pushManager.getSubscription())
      const status = await getPushStatus()
      setPushOn(Boolean(sub) && status.device_count > 0)
    } catch {
      setPushOn(false)
    }
  }

  const togglePush = async () => {
    setPushBusy(true)
    setPushNote('')
    try {
      const push = await import('../api/push')
      if (pushOn) {
        await push.disablePush()
        setPushOn(false)
      } else {
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
      }
    } catch (e) {
      const m = e?.message
      setPushNote(
        m === 'denied'
          ? 'Notifications are blocked for this site. Re-allow them in your browser settings, then try again.'
          : m === 'not-configured'
          ? 'Push is not configured on the server yet.'
          : m === 'unsupported'
          ? 'This browser does not support notifications.'
          : 'Could not change notification settings.'
      )
    } finally {
      setPushBusy(false)
    }
  }

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
                          <div className="notif-section">
                            <p className="notif-section-title">Draw Released Email</p>
                            <p className="notif-section-desc">1 email per week, covering every draw released that week</p>
                            <label className="notif-check-row">
                              <input
                                type="checkbox"
                                checked={notifSelected.has('draw_released')}
                                onChange={() => toggleNotif('draw_released')}
                              />
                              Enabled
                            </label>
                          </div>

                          <div className="notif-section">
                            <p className="notif-section-title">Draw Released Push</p>
                            <p className="notif-section-desc">
                              1 phone notification per week, sent once all that week's draws are out
                            </p>
                            <label className="notif-check-row">
                              <input
                                type="checkbox"
                                checked={pushOn}
                                disabled={pushBusy}
                                onChange={togglePush}
                              />
                              {pushBusy ? 'Working…' : 'Enabled on this device'}
                            </label>
                            {pushNote && <p className="notif-section-desc notif-push-note">{pushNote}</p>}
                          </div>

                          <div className="notif-section">
                            <p className="notif-section-title">Play starts</p>
                            <p className="notif-section-desc">When the first match begins and picks are locked</p>
                            <label className="notif-check-row">
                              <input
                                type="checkbox"
                                checked={notifSelected.has('match_start')}
                                onChange={() => toggleNotif('match_start')}
                              />
                              Enabled
                            </label>
                          </div>

                          <div className="notif-section">
                            <p className="notif-section-title">Round Completion Email</p>
                            <p className="notif-section-desc">1 email per round, summarizing all draws</p>
                            <label className="notif-check-row">
                              <input
                                type="checkbox"
                                checked={notifSelected.has('round_standings')}
                                onChange={toggleRoundStandings}
                              />
                              Enabled
                            </label>
                          </div>

                          {/* Only offered with round emails off — see toggleRoundStandings. */}
                          {!notifSelected.has('round_standings') && (
                            <div className="notif-section">
                              <p className="notif-section-title">Draw Completion</p>
                              <p className="notif-section-desc">One weekly email with final standings for every draw that finished</p>
                              <label className="notif-check-row">
                                <input
                                  type="checkbox"
                                  checked={notifSelected.has('tournament_end')}
                                  onChange={() => toggleNotif('tournament_end')}
                                />
                                Enabled
                              </label>
                            </div>
                          )}

                          <div className="notif-section">
                            <p className="notif-section-title">New member joins your league</p>
                            <p className="notif-section-desc">Email when someone joins a league you own</p>
                            <label className="notif-check-row">
                              <input
                                type="checkbox"
                                checked={notifSelected.has('league_member_joined')}
                                onChange={() => toggleNotif('league_member_joined')}
                              />
                              Enabled
                            </label>
                          </div>

                          {notifError && <p className="profile-edit-error" style={{ padding: '0 1rem' }}>{notifError}</p>}
                          <div className="profile-edit-actions" style={{ padding: '0.5rem 1rem 0.85rem' }}>
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
