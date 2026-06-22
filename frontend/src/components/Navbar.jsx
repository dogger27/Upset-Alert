import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth'
import './Navbar.css'

const DRAW_CATS = [
  { key: 'draw_open:Grand Slam:M', label: 'Grand Slam Men' },
  { key: 'draw_open:Grand Slam:F', label: 'Grand Slam Women' },
  { key: 'draw_open:ATP 1000',     label: 'ATP 1000' },
  { key: 'draw_open:ATP 500',      label: 'ATP 500' },
  { key: 'draw_open:ATP 250',      label: 'ATP 250' },
  { key: 'draw_open:WTA 1000',     label: 'WTA 1000' },
  { key: 'draw_open:WTA 500',      label: 'WTA 500' },
  { key: 'draw_open:WTA 250',      label: 'WTA 250' },
]

export default function Navbar() {
  const { user, logout, updateProfile } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
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

  const menuRef = useRef(null)

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
      setNotifSelected(new Set(data.enabled_keys))
      setNotifLeagues(data.leagues)
    } catch {
      setNotifError('Failed to load preferences')
    } finally {
      setNotifLoading(false)
    }
  }

  const toggleNotif = (key) => {
    setNotifSelected(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
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

  return (
    <nav className="navbar">
      <div className="navbar-left" />
      <Link to="/" className="navbar-brand">
        <span className="navbar-brand-dot" />
        <span className="navbar-brand-text">
          <span className="navbar-brand-upset">Upset</span>{' '}
          <span className="navbar-brand-alert">Alert</span><span className="navbar-brand-exclaim">!</span>
        </span>
      </Link>
      <div className="navbar-links">
        {/^\/tournaments\/[^/]+/.test(location.pathname) && (
          <span className="navbar-label navbar-active">Draw</span>
        )}
        <Link to="/" className={isActive('/') ? 'navbar-active' : ''}>Dashboard</Link>
        <Link to="/about" className={isActive('/about') ? 'navbar-active' : ''}>About</Link>
        {user ? (
          <>
            {user.is_admin && <Link to="/admin" className="navbar-admin-btn">Admin</Link>}
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
                            <p className="notif-section-title">Draw open for selections</p>
                            {DRAW_CATS.map(cat => (
                              <label key={cat.key} className="notif-check-row">
                                <input
                                  type="checkbox"
                                  checked={notifSelected.has(cat.key)}
                                  onChange={() => toggleNotif(cat.key)}
                                />
                                {cat.label}
                              </label>
                            ))}
                          </div>

                          <div className="notif-section">
                            <p className="notif-section-title">Round standings email</p>
                            <label className="notif-check-row">
                              <input
                                type="checkbox"
                                checked={notifSelected.has('round_standings:global')}
                                onChange={() => toggleNotif('round_standings:global')}
                              />
                              Global
                            </label>
                            {notifLeagues.map(lg => (
                              <label key={lg.id} className="notif-check-row">
                                <input
                                  type="checkbox"
                                  checked={notifSelected.has(`round_standings:league:${lg.id}`)}
                                  onChange={() => toggleNotif(`round_standings:league:${lg.id}`)}
                                />
                                {lg.name}
                              </label>
                            ))}
                          </div>

                          <div className="notif-section">
                            <p className="notif-section-title">Tournament complete standings</p>
                            <label className="notif-check-row">
                              <input
                                type="checkbox"
                                checked={notifSelected.has('tournament_end:global')}
                                onChange={() => toggleNotif('tournament_end:global')}
                              />
                              Global
                            </label>
                            {notifLeagues.map(lg => (
                              <label key={lg.id} className="notif-check-row">
                                <input
                                  type="checkbox"
                                  checked={notifSelected.has(`tournament_end:league:${lg.id}`)}
                                  onChange={() => toggleNotif(`tournament_end:league:${lg.id}`)}
                                />
                                {lg.name}
                              </label>
                            ))}
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
