import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import './Navbar.css'

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
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
            <span className="navbar-user">{user.display_name}</span>
            <button className="btn-secondary" onClick={handleLogout}>Log out</button>
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
