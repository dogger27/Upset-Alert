import './About.css'

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
            <h3 className="about-section-title">How It Works</h3>
            <div className="about-grid">
              <div className="about-card">
                <div className="about-card-icon">🎾</div>
                <h4 className="about-card-heading">Pick the Draw</h4>
                <p className="about-card-body">
                  When a tournament draw is released, you predict how far each player will advance.
                  Points are awarded based on how accurate your picks turn out to be, with bigger
                  rewards for calling upsets correctly.
                </p>
              </div>
              <div className="about-card">
                <div className="about-card-icon">🏆</div>
                <h4 className="about-card-heading">Leagues</h4>
                <p className="about-card-body">
                  Create a private league and share an invite code with friends, or compete in
                  the Global league against everyone. Standings are tracked across the full season
                  as tournaments complete.
                </p>
              </div>
              <div className="about-card">
                <div className="about-card-icon">⚡</div>
                <h4 className="about-card-heading">Fully Autonomous</h4>
                <p className="about-card-body">
                  The site runs itself. Draw results are pulled automatically from Wikipedia
                  as matches are played, tournament schedules update on their own, and player
                  seedings and rankings stay current — no admin intervention required.
                </p>
              </div>
            </div>
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
