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
            <img
              className="about-photo"
              src="/paul-wiens.jpg"
              alt="Paul Wiens"
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
            <h3 className="about-section-title">Contact</h3>
            <p className="about-prose">
              Please connect with me for bug fixes, feature requests, or a friendly hello!
            </p>
            <ContactForm />
          </div>

          <div className="about-section">
            <h3 className="about-section-title">Under the Hood</h3>
            <p className="about-prose">
              Tournament draws and match results are sourced from{' '}
              <a href="https://en.wikipedia.org" target="_blank" rel="noopener noreferrer">Wikipedia</a>.
              A background scraper monitors Wikipedia's event stream for edits to tournament pages
              and re-fetches draw data automatically whenever the article changes. This means results
              appear on the site within minutes of being updated on Wikipedia, with no manual step in between.
            </p>
            <p className="about-prose">
              Player seedings are drawn from the ATP and WTA official rankings, and upcoming tournament
              schedules are populated from Wikipedia's season pages at the start of each year. Once
              set up, the whole pipeline runs without any user or admin input — it just works.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
