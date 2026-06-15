import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import './Navbar.css'

export default function Navbar() {
  const { user, logout, updateProfile } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
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
    setError('')
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setError('')
  }

  const saveEdit = async () => {
    setSaving(true)
    setError('')
    try {
      await updateProfile({ username: username.trim() || undefined, full_name: fullName.trim() || undefined })
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

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">🚨 Upset Alert</Link>
      <div className="navbar-links">
        <Link to="/tournaments">Tournaments</Link>
        <Link to="/leagues">Leagues</Link>
        {user ? (
          <>
            <Link to="/admin">Admin</Link>
            <div className="navbar-profile" ref={menuRef}>
              <button
                className="navbar-user"
                onClick={() => { setMenuOpen(s => !s); setEditing(false); setError('') }}
                aria-expanded={menuOpen}
              >
                {user.display_name}
                <span className="navbar-caret" aria-hidden>▾</span>
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
        ) : (
          <>
            <Link to="/login">Log in</Link>
            <Link to="/register" className="btn-primary" style={{ padding: '0.4rem 0.9rem', borderRadius: 6 }}>
              Sign up
            </Link>
          </>
        )}
      </div>
    </nav>
  )
}
