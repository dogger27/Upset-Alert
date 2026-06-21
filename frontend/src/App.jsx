import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './store/auth'
import Navbar from './components/Navbar'
import Home from './pages/Home'
import Login from './pages/Login'
import Register from './pages/Register'
import Tournaments from './pages/Tournaments'
import TournamentDraw from './pages/TournamentDraw'
import LeagueDetail from './pages/LeagueDetail'
import Admin from './pages/Admin'
import About from './pages/About'

function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return children
}

function RequireAdmin({ children }) {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user || !user.is_admin) return <Navigate to="/" replace />
  return children
}

export default function App() {
  const { init } = useAuth()
  useEffect(() => { init() }, [])

  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/tournaments" element={<RequireAdmin><Tournaments /></RequireAdmin>} />
        <Route path="/tournaments/:id" element={<TournamentDraw />} />
        <Route path="/leagues/:id" element={<LeagueDetail />} />
        <Route path="/admin" element={<RequireAdmin><Admin /></RequireAdmin>} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
