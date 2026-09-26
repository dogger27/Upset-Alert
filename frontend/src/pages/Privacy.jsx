import { Link } from 'react-router-dom'
import './About.css'

/* THE PRIVACY POLICY (App Store prep, 2026-09-26). App Store Connect will not
   take a submission without one, and it is the page the listing links to.
   Every line states what the code actually does; when the code changes what
   it keeps or who it shares with, change this page in the same commit. */
export default function Privacy() {
  return (
    <div className="about-page">
      <div className="about-container">
        <div className="about-header">
          <h1 className="about-title">Privacy</h1>
        </div>

        <div className="about-section">
          <p className="about-prose">
            Upset Alert is a tennis prediction game run by one person, Paul Wiens, in Canada.
            This page covers the website at upsetalert.ca and the Upset Alert app. It was last
            updated on 26 September 2026.
          </p>
        </div>

        <div className="about-section">
          <h3 className="about-section-title">What we keep</h3>
          <ul className="about-prose">
            <li><strong>Your account:</strong> email address, username, full name, and a hashed
              password (we never see the password itself). If you add a passkey, we keep its
              public key.</li>
            <li><strong>Your game:</strong> your picks, tiebreak answers, leagues and the
              settings you choose, such as time zone, theme and which notifications you want.</li>
            <li><strong>Your devices:</strong> if you turn on notifications, the token your
              browser or phone gives us for sending them, and a random install ID so one phone
              is not counted twice. The app also keeps the tokens for its Lock Screen live
              scores.</li>
            <li><strong>Server logs:</strong> the IP address of each request, used to stop abuse
              and fix faults, and kept only as long as the logs are.</li>
          </ul>
          <p className="about-prose">
            There is no advertising, no analytics service and no tracking across other apps or
            websites. Nothing is sold.
          </p>
        </div>

        <div className="about-section">
          <h3 className="about-section-title">Who sees it</h3>
          <ul className="about-prose">
            <li><strong>Other players</strong> see your username, your picks once a draw has
              locked, and your standings. Your full name is shown only inside leagues where the
              owner has chosen to show names. Your email address is never shown.</li>
            <li><strong>Services that deliver it:</strong> Resend sends our emails; Apple, Google
              and your browser's maker deliver notifications; Cloudflare carries the traffic to
              the site. Each gets only what that job needs.</li>
          </ul>
        </div>

        <div className="about-section">
          <h3 className="about-section-title">Your choices</h3>
          <ul className="about-prose">
            <li>Turn any email or notification off in your account settings, or with the
              unsubscribe link in any email.</li>
            <li>Delete your account from the account screen, on the site or in the app. Your
              email, name, password, passkeys and devices are deleted immediately. Your picks and
              finishing places stay under an anonymous name that leads back to no one, so other
              players' standings do not change.</li>
            <li>Ask what we hold about you, or ask for anything to be corrected, through
              the <Link to="/support">support page</Link>.</li>
          </ul>
        </div>

        <div className="about-section">
          <h3 className="about-section-title">Children</h3>
          <p className="about-prose">
            Upset Alert is not meant for children under 13, and we do not knowingly keep their
            information. If you believe a child has signed up, tell us and we will delete the
            account.
          </p>
        </div>
      </div>
    </div>
  )
}
