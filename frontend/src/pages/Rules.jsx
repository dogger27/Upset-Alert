import './About.css'

export default function Rules() {
  return (
    <div className="about-page">
      <div className="about-container">
        <div className="about-header">
          <h1 className="about-title">Rules</h1>
        </div>

        <div className="about-body">
          <div className="about-grid" style={{gridTemplateColumns: '1fr'}}>
            <div className="about-card">
              <div className="about-card-icon">🎾</div>
              <h4 className="about-card-heading">Pick the Draw</h4>
              <p className="about-card-body">
                When a tournament draw is released, predict the winner of every match.
                Each correct pick earns points — later rounds are worth more, and
                higher-tier tournaments offer more points.
              </p>
              <table className="about-pts-table">
                <thead>
                  <tr>
                    <th>Tier</th>
                    <th>R128/96</th>
                    <th>R64</th>
                    <th>R32</th>
                    <th>R16</th>
                    <th>QF</th>
                    <th>SF</th>
                    <th>F</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>250</td><td>—</td><td>1</td><td>1</td><td>2</td><td>3</td><td>4</td><td>6</td></tr>
                  <tr><td>500</td><td>—</td><td>1</td><td>1</td><td>2</td><td>4</td><td>8</td><td>12</td></tr>
                  <tr><td>1000</td><td>1</td><td>1</td><td>2</td><td>4</td><td>8</td><td>12</td><td>16</td></tr>
                  <tr><td>Slam</td><td>1</td><td>2</td><td>4</td><td>8</td><td>12</td><td>16</td><td>20</td></tr>
                </tbody>
              </table>
            </div>
            <div className="about-card">
              <div className="about-card-icon">🏆</div>
              <h4 className="about-card-heading">Leagues</h4>
              <p className="about-card-body">
                Create a private league to compete with your friends, or compete in the Global
                league against everyone! Compare your progress by round in the group standings.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
