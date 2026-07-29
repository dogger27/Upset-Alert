import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getH2H, getPlayerForm } from '../api/players'
import './H2HPanel.css'

function teKeys(tournSurface) {
  if (!tournSurface) return []
  const s = tournSurface.toLowerCase()
  if (s.includes('clay')) return ['Clay']
  if (s.includes('grass')) return ['Grass']
  return ['Hard', 'Indoors', 'Carpet']
}

function surfaceLabel(key) {
  if (!key) return '—'
  // Indoor hard courts are treated as "Hard" everywhere on the site; TE reports
  // these as "Indoor"/"Indoors" and fresh scrapes can reintroduce them after the
  // one-off cache migration, so normalize at display time too.
  if (key === 'Indoors' || key === 'Indoor') return 'Hard'
  return key
}

function fmtRound(round) {
  if (!round || round === '—') return '—'
  // Qualifying: "Q-2R" → "Q2"
  const qm = round.match(/^Q-(\d+)R?$/i)
  if (qm) return `Q${qm[1]}`
  // Main draw numbered rounds: "1R" → "R1", "2R" → "R2"
  const rm = round.match(/^(\d+)R$/i)
  if (rm) return `R${rm[1]}`
  return round
}

// TE names come as "Surname Firstname" — move last word to front as fallback
function fmtName(teName) {
  if (!teName) return teName
  const parts = teName.trim().split(/\s+/)
  if (parts.length <= 1) return teName
  return `${parts[parts.length - 1]} ${parts.slice(0, -1).join(' ')}`
}

/** "Alejandro Davidovich Fokina" -> ["Alejandro", "Davidovich Fokina"].
 *  Splits at the FIRST space, so compound surnames stay whole on their line. */
function splitName(full) {
  if (!full) return ['', '']
  const s = full.trim()
  const i = s.indexOf(' ')
  return i === -1 ? [s, ''] : [s.slice(0, i), s.slice(i + 1)]
}

function PlayerName({ player, fallback }) {
  const iso = iocToFlagClass(player?.nationality)
  const [first, last] = splitName(player?.name ?? fmtName(fallback))
  return (
    <>
      {iso && <span className={`fi fi-${iso} h2h-flag`} />}
      <span className="h2h-name-first">{first}</span>
      {last && <span className="h2h-name-last">{last}</span>}
    </>
  )
}

/** The name block, which doubles as this match's pick control.
 *
 *  Rendered as a real <button> only when a pick can actually be made, so the
 *  panel stays inert where the bracket is (locked draws, live mode, someone
 *  else's picks) instead of offering a control that silently does nothing. */
function PickableName({ className, player, fallback, picked, onPick }) {
  const cls = `${className} h2h-player-name${picked ? ' h2h-player-name--picked' : ''}`
  if (!onPick) {
    return <div className={cls}><PlayerName player={player} fallback={fallback} /></div>
  }
  return (
    <button
      type="button"
      className={`${cls} h2h-player-name--pickable`}
      onClick={onPick}
      aria-pressed={picked}
      aria-label={`Pick ${player?.name ?? fallback ?? 'this player'} to win`}
    >
      <PlayerName player={player} fallback={fallback} />
    </button>
  )
}

const IOC_TO_ISO2 = {
  AUS:'AU', USA:'US', GBR:'GB', FRA:'FR', GER:'DE', ESP:'ES', ITA:'IT',
  RUS:'RU', CAN:'CA', JPN:'JP', CHN:'CN', KOR:'KR', ARG:'AR', BRA:'BR',
  SUI:'CH', AUT:'AT', BEL:'BE', NED:'NL', DEN:'DK', NOR:'NO', SWE:'SE',
  FIN:'FI', POL:'PL', CZE:'CZ', SVK:'SK', HUN:'HU', ROU:'RO', BUL:'BG',
  SRB:'RS', CRO:'HR', SLO:'SI', BIH:'BA', MKD:'MK', GRE:'GR', TUR:'TR',
  POR:'PT', GEO:'GE', KAZ:'KZ', UKR:'UA', BLR:'BY', LAT:'LV', LTU:'LT',
  EST:'EE', ISR:'IL', RSA:'ZA', EGY:'EG', MAR:'MA', TUN:'TN', NGR:'NG',
  CHI:'CL', COL:'CO', PER:'PE', URU:'UY', VEN:'VE', ECU:'EC', BOL:'BO',
  PAR:'PY', MEX:'MX', IND:'IN', PAK:'PK', THA:'TH', VIE:'VN', INA:'ID',
  MAS:'MY', PHI:'PH', TPE:'TW', HKG:'HK', NZL:'NZ', BAH:'BS', DOM:'DO',
  HAI:'HT', PUR:'PR', TTO:'TT', JAM:'JM', BAR:'BB', GUA:'GT', CRC:'CR',
  MON:'MC', LUX:'LU', ISL:'IS', IRL:'IE', CYP:'CY', MLT:'MT',
  ALG:'DZ', MDA:'MD', ARM:'AM', AZE:'AZ', UZB:'UZ', KGZ:'KG', TJK:'TJ',
  TKM:'TM', BIZ:'BZ', PAN:'PA', NCA:'NI', ESA:'SV', HON:'HN',
}

function iocToFlagClass(ioc) {
  if (!ioc) return null
  const iso = IOC_TO_ISO2[ioc.toUpperCase()]
  return iso ? iso.toLowerCase() : null
}

function calcAge(dob) {
  if (!dob) return null
  const today = new Date()
  const birth = new Date(dob)
  let age = today.getFullYear() - birth.getFullYear()
  const mo = today.getMonth() - birth.getMonth()
  if (mo < 0 || (mo === 0 && today.getDate() < birth.getDate())) age--
  return age
}

function bestCls(val, other, lowerIsBetter = false) {
  if (val == null || other == null || val === other) return ''
  return (lowerIsBetter ? val < other : val > other) ? 'h2h-best' : ''
}

function flipScore(score) {
  if (!score) return score
  return score.split(', ').map(set => {
    const parts = set.split('-')
    if (parts.length !== 2) return set
    return `${parts[1]}-${parts[0]}`
  }).join(', ')
}

function fmtFormDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Must match .h2h-form-popup's width in H2HPanel.css — the clamp in open()
// needs the width in JS, so it is fixed there rather than sized by content.
const FORM_POPUP_W = 230
const FORM_POPUP_EDGE = 8

// Longest the panel will keep showing the previous match while waiting for the
// next one's data. Past this the wait is doing more harm than the flicker it
// avoids — see the commit effect in H2HPanel.
const SWAP_WAIT_MS = 2500

function FormBox({ m }) {
  const ref = useRef(null)
  const [pos, setPos] = useState(null)

  const open = () => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    // The popup is centred on the square it belongs to, which pushes it off
    // screen for the squares at either end of a row — the leftmost one hid its
    // own labels past the left edge. Clamp the centre so the popup always lands
    // inside the viewport; it keeps pointing at the right square because it is
    // wider than the gap it moves by. FORM_POPUP_W must match the width set in
    // H2HPanel.css, which is why that width is fixed rather than content-driven.
    const half = FORM_POPUP_W / 2
    const limit = window.innerWidth - half - FORM_POPUP_EDGE
    const min = half + FORM_POPUP_EDGE
    const centre = r.left + r.width / 2
    setPos({
      // On a screen too narrow to hold the popup at all, min > limit — centre it.
      x: min > limit ? window.innerWidth / 2 : Math.min(Math.max(centre, min), limit),
      y: r.top,
    })
  }

  // Dismiss on the next touch anywhere. Registered only while a popup is open,
  // and on touchstart rather than click so it fires before the backdrop's own
  // click handler can close the whole panel out from under the reader.
  useEffect(() => {
    if (!pos) return
    const away = () => setPos(null)
    document.addEventListener('touchstart', away, { passive: true })
    return () => document.removeEventListener('touchstart', away)
  }, [pos])

  if (!m) return <span className="h2h-form-box h2h-form-box--empty" />

  return (
    <>
      <span
        ref={ref}
        className={`h2h-form-box ${m.result === 'W' ? 'h2h-form-box--win' : 'h2h-form-box--loss'}`}
        onMouseEnter={open}
        onMouseLeave={() => setPos(null)}
        // Touch has no hover, so these squares were pure decoration on a phone —
        // the match behind each result was unreachable. Tap opens the same popup.
        onTouchStart={e => { e.stopPropagation(); pos ? setPos(null) : open() }}
      >
        {m.result}
      </span>
      {pos && createPortal(
        <div className="h2h-form-popup" style={{ position: 'fixed', left: pos.x, top: pos.y - 8, transform: 'translate(-50%, -100%)' }}>
          <div className="h2h-form-popup-event">{[m.event, m.round].filter(Boolean).join(' · ')}</div>
          <div className="h2h-form-popup-row"><span>vs</span><strong>{m.opponent}</strong></div>
          <div className="h2h-form-popup-row"><span>Score</span><strong>{m.score || '—'}</strong></div>
          <div className="h2h-form-popup-row"><span>Date</span><strong>{fmtFormDate(m.date)}</strong></div>
        </div>,
        document.body
      )}
    </>
  )
}

function FormRow({ matches }) {
  const boxes = Array.from({ length: 10 }, (_, i) => matches?.[i] ?? null)
  return (
    <div className="h2h-form-row">
      {boxes.map((m, i) => <FormBox key={i} m={m} />)}
    </div>
  )
}

function EloInfoPopup({ onClose }) {
  return (
    <div className="h2h-elo-popup-backdrop" onClick={onClose}>
      <div className="h2h-elo-popup" onClick={e => e.stopPropagation()}>
        <div className="h2h-elo-popup-header">
          <span className="h2h-elo-popup-title">About Elo Rating</span>
          <button className="h2h-elo-popup-close" onClick={onClose}>✕</button>
        </div>
        <p className="h2h-elo-popup-body">
          Elo measures a player's overall career strength based on match results,
          weighted by opponent quality. A win over a top-10 player boosts your
          rating more than a win over a qualifier. The rank shown is each player's
          position among all active players on tour — #1 is the strongest.
        </p>
        <p className="h2h-elo-popup-source">Source: tennisabstract.com · Updated weekly</p>
      </div>
    </div>
  )
}

export default function H2HPanel({
  // Suffixed "In" so the difference is impossible to miss: these describe the
  // match being navigated TO. Everything rendered below comes from `view`.
  slug1: slug1In, slug2: slug2In, player1: player1In, player2: player2In,
  beforeDrawId: beforeDrawIdIn, beforeRound: beforeRoundIn, match: matchIn = null,
  tournSurface, tournGender, onClose,
  picks = null, onPick = null, canPick = false, onPrev = null, onNext = null,
}) {
  const [surfFilter, setSurfFilter] = useState('all') // 'all' | 'surface'
  const [showEloInfo, setShowEloInfo] = useState(false)

  // The queries are keyed on the INCOMING match so navigation starts fetching
  // straight away, but keepPreviousData means they keep serving the match
  // currently on screen until the new one has arrived.
  const { data, isLoading, isError, isPlaceholderData } = useQuery({
    queryKey: ['h2h', slug1In, slug2In],
    queryFn: () => getH2H(slug1In, slug2In),
    staleTime: 15 * 60 * 1000,
    placeholderData: keepPreviousData,
  })

  // Form is sourced from our own db (not the TE scrape behind getH2H above), so
  // fetch it independently — it should render immediately, not wait on get_h2h.
  // beforeDrawId/beforeRound restrict Form to results before that match's date,
  // so viewing an old draw shows form leading up to it, not each player's
  // current form.
  const { data: form_p1, isPlaceholderData: f1Stale } = useQuery({
    queryKey: ['h2h-form', slug1In, beforeDrawIdIn, beforeRoundIn],
    queryFn: () => getPlayerForm(slug1In, { beforeDrawId: beforeDrawIdIn, beforeRound: beforeRoundIn }),
    enabled: !!slug1In,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  })
  const { data: form_p2, isPlaceholderData: f2Stale } = useQuery({
    queryKey: ['h2h-form', slug2In, beforeDrawIdIn, beforeRoundIn],
    queryFn: () => getPlayerForm(slug2In, { beforeDrawId: beforeDrawIdIn, beforeRound: beforeRoundIn }),
    enabled: !!slug2In,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  })

  // Everything rendered comes from `view`, never from the *In props.
  //
  // Arrowing to the next match used to swap the props immediately, which blew
  // every field away and refilled it a moment later — the panel visibly
  // collapsed and jumped. Now the incoming match is held back until all three
  // queries have it, then the whole panel changes at once. While it's in flight
  // the previous match stays on screen intact, because the queries are still
  // serving its data.
  //
  // isPlaceholderData means exactly "this data belongs to the previous key", so
  // committing only when all three are false is what stops the names, the H2H
  // numbers and the two form rows from ever describing different matches.
  const incomingRef = useRef(null)
  incomingRef.current = {
    slug1: slug1In, slug2: slug2In, player1: player1In, player2: player2In,
    match: matchIn, beforeDrawId: beforeDrawIdIn, beforeRound: beforeRoundIn,
  }

  const settling = isPlaceholderData || f1Stale || f2Stale
  const [view, setView] = useState(() => incomingRef.current)

  useEffect(() => {
    if (!settling) {
      setView(incomingRef.current)
      return
    }
    // Holding the old match is only right while the new one is genuinely on its
    // way. A slow or retrying query would otherwise strand the panel on the
    // previous match with the arrows appearing to do nothing at all, which is a
    // worse failure than the flicker this replaces. Give up waiting and show
    // the new match with its fields filling in.
    const t = setTimeout(() => setView(incomingRef.current), SWAP_WAIT_MS)
    return () => clearTimeout(t)
  }, [settling, slug1In, slug2In, matchIn?.id])

  const { slug1, slug2, player1, player2, match, beforeDrawId, beforeRound } = view
  const pickedId = picks && match ? (picks[match.id] ?? null) : null
  const showForm = (form_p1?.length ?? 0) > 0 || (form_p2?.length ?? 0) > 0

  const slug1IsA = data ? slug1 === data.slug_a : true
  const name_p1 = slug1IsA ? data?.name_a : data?.name_b
  const name_p2 = slug1IsA ? data?.name_b : data?.name_a
  const wins_p1 = slug1IsA ? data?.wins_a : data?.wins_b
  const wins_p2 = slug1IsA ? data?.wins_b : data?.wins_a

  const rank_p1 = player1?.ranking ?? null
  const rank_p2 = player2?.ranking ?? null
  const elo_rank_p1 = player1?.elo_rank ?? null
  const elo_rank_p2 = player2?.elo_rank ?? null
  const age_p1 = calcAge(player1?.date_of_birth)
  const age_p2 = calcAge(player2?.date_of_birth)

  const surfKeys = teKeys(tournSurface)
  let surf_p1 = 0, surf_p2 = 0
  if (data?.surface_wins) {
    for (const key of surfKeys) {
      const sw = data.surface_wins[key]
      if (sw) {
        surf_p1 += slug1IsA ? sw[0] : sw[1]
        surf_p2 += slug1IsA ? sw[1] : sw[0]
      }
    }
  }
  const hasSurfData = (surf_p1 + surf_p2) > 0
  const surfLabel = surfKeys.length ? surfaceLabel(surfKeys[0]) : ''

  const matches = data?.matches ?? []
  const displayMatches = surfFilter === 'surface'
    ? matches.filter(m => surfKeys.includes(m.surface))
    : matches
  const showRank = rank_p1 != null || rank_p2 != null
  const showElo = elo_rank_p1 != null || elo_rank_p2 != null
  const showAge = age_p1 != null || age_p2 != null

  return createPortal(
    <div className="h2h-backdrop" onClick={onClose}>
      {showEloInfo && <EloInfoPopup onClose={() => setShowEloInfo(false)} />}
      <div className="h2h-panel" onClick={e => e.stopPropagation()}>
        {/* Arrows paired at the left with the title to their right, matching
            the draw header's own nav bar rather than inventing a second
            arrangement for the same gesture. */}
        <div className="h2h-navbar">
          <div className="h2h-nav-arrows">
            <button
              className="h2h-nav-btn"
              onClick={onPrev || undefined}
              disabled={!onPrev}
              aria-label="Previous match"
            >‹</button>
            <button
              className="h2h-nav-btn"
              onClick={onNext || undefined}
              disabled={!onNext}
              aria-label="Next match"
            >›</button>
          </div>
          <span className="h2h-round-name">{match?.round_name || ''}</span>
          <button className="h2h-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Each stat is its own grid row. Desktop lays it out as
            [label][p1][vs][p2]; on mobile the label reorders into the centre
            channel so the two players sit against the edges — see H2HPanel.css.
            The rows have to be separate grids for that reorder to be possible:
            in one flat grid, `order` can't move an item within its own row. */}
        <div className="h2h-header">
          {/* Names row — always use our API names (Firstname Lastname order) */}
          <div className="h2h-row h2h-row--names">
            <div className="h2h-label" />
            <PickableName
              className="h2h-col-val h2h-val-p1"
              player={player1} fallback={name_p1}
              picked={pickedId != null && pickedId === player1?.id}
              onPick={canPick && player1?.id != null ? () => onPick(match.id, player1.id) : null}
            />
            <div className="h2h-vs">vs</div>
            <PickableName
              className="h2h-col-val h2h-val-p2"
              player={player2} fallback={name_p2}
              picked={pickedId != null && pickedId === player2?.id}
              onPick={canPick && player2?.id != null ? () => onPick(match.id, player2.id) : null}
            />
          </div>

          {/* Overall row — click to show all matches. Rendered immediately;
              values show a loading placeholder until the (possibly slow, TE-scraped) data arrives. */}
          <div className="h2h-row">
            <button
              className={`h2h-label h2h-filter-btn${surfFilter === 'all' ? ' h2h-filter-active' : ''}`}
              onClick={() => setSurfFilter('all')}
            >Overall</button>
            <div className="h2h-col-val h2h-val-p1 h2h-wins"><span className={bestCls(wins_p1, wins_p2)}>{isLoading ? '⋯' : (wins_p1 ?? '—')}</span></div>
            <div className="h2h-vs" />
            <div className="h2h-col-val h2h-val-p2 h2h-wins"><span className={bestCls(wins_p2, wins_p1)}>{isLoading ? '⋯' : (wins_p2 ?? '—')}</span></div>
          </div>

          {/* Surface row — click to filter matches by surface */}
          {surfKeys.length > 0 && (
            <div className="h2h-row">
              <button
                className={`h2h-label h2h-filter-btn${surfFilter === 'surface' ? ' h2h-filter-active' : ''}`}
                onClick={() => setSurfFilter('surface')}
              >{surfLabel}</button>
              <div className="h2h-col-val h2h-val-p1 h2h-wins"><span className={bestCls(surf_p1, surf_p2)}>{isLoading ? '⋯' : surf_p1}</span></div>
              <div className="h2h-vs" />
              <div className="h2h-col-val h2h-val-p2 h2h-wins"><span className={bestCls(surf_p2, surf_p1)}>{isLoading ? '⋯' : surf_p2}</span></div>
            </div>
          )}

          {/* Divider */}
          <div className="h2h-divider" />

          {/* Rank row */}
          {showRank && (
            <div className="h2h-row">
              <div className="h2h-label">{tournGender === 'F' ? 'Rank (WTA)' : 'Rank (ATP)'}</div>
              <div className="h2h-col-val h2h-val-p1 h2h-meta-val"><span className={bestCls(rank_p1, rank_p2, true)}>{rank_p1 != null ? `#${rank_p1}` : '—'}</span></div>
              <div className="h2h-vs" />
              <div className="h2h-col-val h2h-val-p2 h2h-meta-val"><span className={bestCls(rank_p2, rank_p1, true)}>{rank_p2 != null ? `#${rank_p2}` : '—'}</span></div>
            </div>
          )}

          {/* Elo row */}
          {showElo && (
            <div className="h2h-row">
              <div className="h2h-label h2h-label-with-info">
                Rank (Elo)
                <button className="h2h-info-btn" onClick={e => { e.stopPropagation(); setShowEloInfo(true) }} aria-label="About Elo">ⓘ</button>
              </div>
              <div className="h2h-col-val h2h-val-p1 h2h-meta-val"><span className={bestCls(elo_rank_p1, elo_rank_p2, true)}>{elo_rank_p1 != null ? `#${elo_rank_p1}` : '—'}</span></div>
              <div className="h2h-vs" />
              <div className="h2h-col-val h2h-val-p2 h2h-meta-val"><span className={bestCls(elo_rank_p2, elo_rank_p1, true)}>{elo_rank_p2 != null ? `#${elo_rank_p2}` : '—'}</span></div>
            </div>
          )}

          {/* Age row */}
          {showAge && (
            <div className="h2h-row">
              <div className="h2h-label">Age</div>
              <div className="h2h-col-val h2h-val-p1 h2h-meta-val">{age_p1 ?? '—'}</div>
              <div className="h2h-vs" />
              <div className="h2h-col-val h2h-val-p2 h2h-meta-val">{age_p2 ?? '—'}</div>
            </div>
          )}

          {/* Form row — last 10 results, most recent first */}
          {showForm && (
            <div className="h2h-row h2h-row--form">
              <div className="h2h-label">Form</div>
              <div className="h2h-col-val h2h-val-p1"><FormRow matches={form_p1} /></div>
              <div className="h2h-vs" />
              <div className="h2h-col-val h2h-val-p2"><FormRow matches={form_p2} /></div>
            </div>
          )}
        </div>

        {isLoading && <div className="h2h-loading">Loading H2H data…</div>}
        {isError && <div className="h2h-error">Could not load H2H data.</div>}

        {data && !isLoading && (
          matches.length > 0 ? (
            <div className="h2h-table-wrap">
              {/* Mobile hides the column headers (six columns don't fit), which
                  left the list with nothing naming it. This caption replaces
                  them there — and, because Overall/Hard filter this list, it
                  also surfaces the active filter, which is otherwise invisible
                  once the headers are gone. Hidden on desktop. */}
              <div className="h2h-list-title">
                {displayMatches.length} previous {displayMatches.length === 1 ? 'meeting' : 'meetings'}
                {surfFilter === 'surface' && surfLabel ? ` · ${surfLabel}` : ''}
              </div>
              <table className="h2h-table">
                <thead>
                  <tr>
                    <th>Score</th>
                    <th>Winner</th>
                    <th>Surface</th>
                    <th>Year</th>
                    <th>Tournament</th>
                    <th>Rnd</th>
                  </tr>
                </thead>
                <tbody>
                  {displayMatches.map((m, idx) => {
                    const isWin = slug1IsA ? m.winner === 'a' : m.winner === 'b'
                    const displayScore = slug1IsA ? m.score : flipScore(m.score)
                    const winnerIsP1 = slug1IsA ? m.winner === 'a' : m.winner === 'b'
                    const winnerName = winnerIsP1
                      ? (player1?.name ?? fmtName(data.name_a))
                      : (player2?.name ?? fmtName(data.name_b))
                    return (
                      <tr key={idx} className={isWin ? 'h2h-row-win' : 'h2h-row-loss'}>
                        <td className="h2h-score">{displayScore || '—'}</td>
                        <td className="h2h-winner">{winnerName}</td>
                        <td className="h2h-surface">{surfaceLabel(m.surface)}</td>
                        <td className="h2h-year">{m.year ?? '—'}</td>
                        <td className="h2h-tourn">{m.tournament ?? '—'}</td>
                        <td className="h2h-round">{fmtRound(m.round)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="h2h-empty">No head-to-head matches found.</div>
          )
        )}
      </div>
    </div>,
    document.body
  )
}
