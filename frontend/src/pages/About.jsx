import { useState } from 'react'
import client from '../api/client'
import './About.css'

function ContactForm() {
  const [form, setForm] = useState({ name: '', email: '', subject: '', body: '' })
  const [status, setStatus] = useState('idle') // 'idle' | 'sending' | 'sent' | 'error'

  const set = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setStatus('sending')
    try {
      await client.post('/contact', form)
      setStatus('sent')
    } catch {
      setStatus('error')
    }
  }

  if (status === 'sent') {
    return (
      <div className="contact-success">
        Message sent! I'll get back to you soon.
      </div>
    )
  }

  return (
    <form className="contact-form" onSubmit={handleSubmit} noValidate>
      <div className="contact-row">
        <div className="contact-field">
          <label className="contact-label">Name</label>
          <input
            className="contact-input"
            type="text"
            value={form.name}
            onChange={set('name')}
            required
            autoComplete="name"
          />
        </div>
        <div className="contact-field">
          <label className="contact-label">Your Email</label>
          <input
            className="contact-input"
            type="email"
            value={form.email}
            onChange={set('email')}
            required
            autoComplete="email"
          />
        </div>
      </div>
      <div className="contact-field">
        <label className="contact-label">Subject</label>
        <input
          className="contact-input"
          type="text"
          value={form.subject}
          onChange={set('subject')}
          required
        />
      </div>
      <div className="contact-field">
        <label className="contact-label">Message</label>
        <textarea
          className="contact-textarea"
          value={form.body}
          onChange={set('body')}
          rows={5}
          required
        />
      </div>
      {status === 'error' && (
        <p className="contact-error">Something went wrong — please try again.</p>
      )}
      <button
        className="contact-submit"
        type="submit"
        disabled={status === 'sending' || !form.name || !form.email || !form.subject || !form.body}
      >
        {status === 'sending' ? 'Sending…' : 'Send Message'}
      </button>
    </form>
  )
}

export default function About() {
  return (
    <div className="about-page">
      <div className="about-container">
        <div className="about-header">
          <h1 className="about-title">About</h1>
        </div>

        <div className="about-body">
          <div className="about-bio-card">
            {/* 720px wide, ~75 KB. The original is 4024px and 4 MB, which
                every phone was downloading to fill a 340px box. */}
            <img
              className="about-photo"
              src="/paul-wiens-720.jpg"
              alt="Paul Wiens"
              width="720" height="1082"
              loading="lazy" decoding="async"
            />
            <div className="about-bio-text">
              <h2 className="about-name">Paul Wiens</h2>
              <p className="about-tagline">Tennis enthusiast · Stats nerd · Developer at ILM / Disney</p>
              <p className="about-desc">
                Upset Alert! is a hobby project born out of a love for tennis and the fun of picking tournament
                draws with friends. It's completely free to play — create a league, invite your crew, and see
                who can predict the most upsets.
              </p>
              <p className="about-desc">
                I built this for the community to enjoy. No subscriptions, no ads, no catches.
              </p>
            </div>
          </div>

          <div className="about-section">
            <h3 className="about-section-title">Add to Your Home Screen</h3>
            <p className="about-prose">
              Upset Alert runs in your browser — there is nothing to download. Add it to your
              home screen and it opens full screen like any other app, keeps you signed in, and
              can notify you the moment a draw is released.
            </p>
            <p className="about-install-lede">
              Opened this from a link inside another app — WhatsApp, Instagram, Facebook? Those
              browsers can’t add anything at all. Choose <strong>“Open in Safari”</strong> or
              <strong> “Open in browser”</strong> from that app’s menu first, then follow the
              steps below.
            </p>
            {/* <details>, not a JS toggle: closed by default for free, keyboard
                and screen-reader accessible for free, and it still opens if the
                page's JavaScript never arrives.

                Safari and Chrome get their OWN set on iPhone. The first two
                taps genuinely differ — Safari hides Share inside the ••• menu
                at the bottom, Chrome puts it in the address bar at the top —
                and one merged set had to hedge, which is how a reader ends up
                looking for a button that is not on their screen. */}
            <details className="about-install">
              <summary className="about-install-head">
                <span className="about-install-os">iPhone &amp; iPad</span>
                <span className="about-install-meta">Safari</span>
              </summary>
              <ol className="about-install-steps">
                <li>
                  Tap the <strong>•••</strong> button at the <strong>bottom</strong> of the screen.
                  Don’t see the bar? Scroll up, or tap the very bottom once to bring it back.
                  <img className="about-install-shot" src="/install/safari-more.jpg" loading="lazy" decoding="async"
                       alt="Safari’s bottom bar, with the ••• button at its right end ringed" />
                </li>
                <li>
                  Tap <strong>“Share”</strong> at the top of that menu.
                  <img className="about-install-shot" src="/install/safari-share.jpg" loading="lazy" decoding="async"
                       alt="Safari’s menu, with Share at the top ringed" />
                </li>
                <li>
                  Scroll down that list and tap <strong>“Add to Home Screen”</strong>.
                  <img className="about-install-shot" src="/install/add-to-home.jpg" loading="lazy" decoding="async"
                       alt="The share sheet scrolled down, with Add to Home Screen ringed" />
                </li>
                <li>
                  Tap <strong>“Add”</strong>, top right. Upset Alert is now an icon on your Home
                  Screen — open it from there.
                </li>
              </ol>
            </details>
            <details className="about-install">
              <summary className="about-install-head">
                <span className="about-install-os">iPhone &amp; iPad</span>
                <span className="about-install-meta">Chrome</span>
              </summary>
              <ol className="about-install-steps">
                <li>
                  Tap the Share button in the address bar, at the <strong>top</strong> of the screen.
                  <img className="about-install-shot" src="/install/chrome-share.jpg" loading="lazy" decoding="async"
                       alt="Chrome’s address bar, with the Share button at its right end ringed" />
                </li>
                <li>
                  Scroll down that list and tap <strong>“Add to Home Screen”</strong>.
                  <img className="about-install-shot" src="/install/add-to-home.jpg" loading="lazy" decoding="async"
                       alt="The share sheet scrolled down, with Add to Home Screen ringed" />
                </li>
                <li>
                  Tap <strong>“Add”</strong>, top right. Upset Alert is now an icon on your Home
                  Screen — open it from there.
                </li>
              </ol>
            </details>
            <details className="about-install">
              <summary className="about-install-head">
                <span className="about-install-os">Android</span>
                <span className="about-install-meta">Chrome</span>
              </summary>
              <ol className="about-install-steps">
                <li>Tap the <strong>⋮</strong> menu in the top right.</li>
                <li>Tap <strong>“Install app”</strong> — some phones say <strong>“Add to Home screen”</strong>.</li>
                <li>Tap <strong>“Install”</strong> to confirm. Upset Alert is now an icon on your home screen.</li>
              </ol>
              <p className="about-install-note">
                Some phones offer the same thing as a banner at the bottom of the screen the
                first time you visit. Either way gets you the same app.
              </p>
            </details>
          </div>

          <div className="about-section">
            <h3 className="about-section-title">Contact</h3>
            <p className="about-prose">
              Please connect with me for bug fixes, feature requests, or a friendly hello!
            </p>
            <ContactForm />
          </div>

          <div className="about-section">
            <h3 className="about-section-title">Under the Hood</h3>
            <div className="about-grid">
              <div className="about-card">
                <div className="about-card-icon">🌐</div>
                <h4 className="about-card-heading">Data Sources</h4>
                <p className="about-card-body">
                  <a href="https://en.wikipedia.org" target="_blank" rel="noopener noreferrer">Wikipedia</a>: Tournament Data &amp; Draws
                  <br />
                  <a href="https://www.sofascore.com" target="_blank" rel="noopener noreferrer">Sofascore</a>: Live Point-by-Point Scores &amp; Match Results
                  <br />
                  <a href="https://www.espn.com" target="_blank" rel="noopener noreferrer">ESPN</a>: Live Score &amp; Results Cross-Check
                  <br />
                  ATP/WTA Official Order of Play: Daily Schedules
                  <br />
                  <a href="https://www.tennisexplorer.com" target="_blank" rel="noopener noreferrer">Tennis Explorer</a>: Weekly Rankings, Elo &amp; Player Data
                </p>
              </div>
              <div className="about-card">
                <div className="about-card-icon">⚡</div>
                <h4 className="about-card-heading">Fully Autonomous</h4>
                <p className="about-card-body">
                  The site runs itself. Draw results, tournament schedules, player seedings,
                  and rankings all stay current automatically — and every published schedule
                  is verified against the official sheet by an autonomous AI agent that
                  repairs what it finds. No admin intervention required.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
