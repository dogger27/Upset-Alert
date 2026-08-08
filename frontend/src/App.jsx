import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './store/auth'
import Navbar from './components/Navbar'
import InstallPrompt from './components/InstallPrompt'
import Home from './pages/Home'
import Login from './pages/Login'
import Register from './pages/Register'
import Tournaments from './pages/Tournaments'
import TournamentDraw from './pages/TournamentDraw'
import Leagues from './pages/Leagues'
import LeagueDetail from './pages/LeagueDetail'
import Admin from './pages/Admin'
import About from './pages/About'
import DrawHistory from './pages/DrawHistory'
import HallOfFame from './pages/HallOfFame'
import Rules from './pages/Rules'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import VerifyEmail from './pages/VerifyEmail'

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
  const { init, user } = useAuth()
  useEffect(() => { init() }, [])

  // Tell the server this account is running the INSTALLED app. Standalone mode
  // is the only moment a PWA install is observable at all — nothing about the
  // install itself reaches the server — so without this the admin "Mobile"
  // column can only ever reflect push registrations, which misses anyone who
  // installed the app but never enabled notifications.
  //
  // Once per session: the fact doesn't change while the app is open, and a
  // request on every route change would be pure noise. Fire-and-forget, since
  // nothing in the UI depends on it.
  useEffect(() => {
    if (!user) return
    const standalone =
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true
    if (!standalone) return
    if (sessionStorage.getItem('ua-app-open-sent')) return
    sessionStorage.setItem('ua-app-open-sent', '1')
    import('./api/client').then(({ default: client }) => {
      client.post('/auth/me/app-open').catch(() => {})
    })
  }, [user])

  return (
    <>
      <Navbar />
      <InstallPrompt />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/tournaments" element={<RequireAdmin><Tournaments /></RequireAdmin>} />
        <Route path="/tournaments/:id" element={<TournamentDraw />} />
        <Route path="/leagues" element={<Leagues />}>
          <Route index element={<LeagueDetail />} />
          <Route path=":id" element={<LeagueDetail />} />
        </Route>
        <Route path="/admin" element={<RequireAdmin><Admin /></RequireAdmin>} />
        <Route path="/about" element={<About />} />
        <Route path="/draw-history" element={<DrawHistory />} />
        <Route path="/hall-of-fame" element={<HallOfFame />} />
        <Route path="/rules" element={<Rules />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
