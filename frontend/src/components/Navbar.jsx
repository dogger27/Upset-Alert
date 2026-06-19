import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth'
import './Navbar.css'

export default function Navbar() {
  const { user, logout, updateProfile } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
        setEditing(false)
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
          <span className="navbar-brand-alert">Alert</span>
        </span>
      </Link>
      <div className="navbar-links">
        {/^\/tournaments\/[^/]+/.test(location.pathname) && (
          <Link to="/" className="">Dashboard</Link>
        )}
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
                  {!editing ? (
                    <>
                      <div className="profile-dropdown-header">
                        <span className="profile-dropdown-name">{user.display_name}</span>
                        <span className="profile-dropdown-email">{user.email}</span>
                      </div>
                      <div className="profile-dropdown-divider" />
                      <button className="profile-dropdown-item" onClick={openEdit}>
                        Edit profile
                      </button>
                      <div className="profile-dropdown-divider" />
                      <button className="profile-dropdown-item profile-dropdown-item--danger" onClick={handleLogout}>
                        Log out
                      </button>
                    </>
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
