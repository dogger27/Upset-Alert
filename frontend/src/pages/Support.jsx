import { Link } from 'react-router-dom'
import { ContactForm } from './About'
import './About.css'

/* SUPPORT (App Store prep, 2026-09-26): the support link the App Store listing
   requires. It is the About page's contact form on a page of its own, so the
   link lands on the form and not halfway down a biography. */
export default function Support() {
  return (
    <div className="about-page">
      <div className="about-container">
        <div className="about-header">
          <h1 className="about-title">Support</h1>
        </div>
        <div className="about-section">
          <p className="about-prose">
            Something not working, a question about your account, or an idea? Send a message
            and I will reply by email. How scoring works is on the <Link to="/rules">rules
            page</Link>, and what we keep about you is on the <Link to="/privacy">privacy
            page</Link>.
          </p>
          <ContactForm />
        </div>
      </div>
    </div>
  )
}
