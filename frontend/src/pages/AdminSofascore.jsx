/* THE SOFASCORE REQUEST LEDGER, DRAWN (owner, 2026-09-26). Every request we
   send Sofascore is recorded (backend services/sofa_ledger.py) so that a block
   can be explained after the fact and a rate creeping toward one can be seen
   before it. This is that record as a picture: whether we are blocked now,
   the rate against its budget, who is asking, and what we sent before each
   block. Reads /admin/sofascore-requests; sends nothing to Sofascore.

   EVERY SOURCE, ONE VIEW (owner, 2026-09-26): protennislive and Tennis
   Explorer are recorded the same way (backend services/request_ledger), and
   the switch at the top reads /admin/requests?source=. protennislive's limit
   is per IP per ten minutes, so it gets a tile for its busiest ten minutes
   against that limit. */
import { useEffect, useMemo, useState } from 'react'
import './AdminSofascore.css'

const SOURCES = [
  { key: 'sofascore', label: 'Sofascore' },
  { key: 'protennislive', label: 'protennislive' },
  { key: 'tennisexplorer', label: 'Tennis Explorer' },
]

const WINDOWS = [
  { label: '1 hour', minutes: 60 },
  { label: '6 hours', minutes: 360 },
  { label: '24 hours', minutes: 1440 },
  { label: '7 days', minutes: 10080 },
]

// One colour per caller, in order of volume; the rest share the last.
const CALLER_COLOURS = [
  'var(--green-500)', 'var(--clay-500)', 'var(--atp-500)',
  'var(--info)', 'var(--gold-ink)', 'var(--ink-400)',
]

const asDate = (t) => (t ? new Date(t) : null)
const clock = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
const dayClock = (d) => d.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })

function ago(d) {
  if (!d) return 'never'
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000)
  if (s < 90) return `${Math.round(s)} s ago`
  if (s < 90 * 60) return `${Math.round(s / 60)} min ago`
  if (s < 48 * 3600) return `${(s / 3600).toFixed(1)} h ago`
  return `${Math.round(s / 86400)} days ago`
}

function span(seconds) {
  if (seconds < 90) return `${Math.round(seconds)} s`
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} h`
}

function budgetFor(caller, budgets) {
  const svc = caller.split('.')[0]
  return budgets?.callers?.[svc] ?? budgets?.caller_default ?? null
}

function statusClass(st) {
  if (st === 403 || st === 429) return 'sofa-st sofa-st--blocked'
  if (typeof st === 'number' && ((st >= 200 && st < 300) || st === 404)) return 'sofa-st sofa-st--ok'
  return 'sofa-st sofa-st--failed'
}

/* Snapshot files are named block-20260925T100700Z.jsonl. */
function snapshotTime(file) {
  const m = /block-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z/.exec(file || '')
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])) : null
}

export default function SofascorePanel() {
  const [source, setSource] = useState('sofascore')
  const [minutes, setMinutes] = useState(1440)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [loadedAt, setLoadedAt] = useState(null)

  useEffect(() => {
    let live = true
    const load = async () => {
      try {
        const { default: client } = await import('../api/client')
        const res = (await client.get('/admin/requests', { params: { source, minutes, recent: 100 } })).data
        if (live) { setData(res); setErr(''); setLoadedAt(new Date()) }
      } catch {
        if (live) setErr('Could not load the request ledger')
      }
    }
    load()
    const id = setInterval(load, 60000)
    return () => { live = false; clearInterval(id) }
  }, [source, minutes])

  const callers = useMemo(() => Object.entries(data?.summary?.by_caller || {}), [data])
  const colourOf = useMemo(() => {
    const map = {}
    callers.forEach(([c], i) => { map[c] = CALLER_COLOURS[Math.min(i, CALLER_COLOURS.length - 1)] })
    return map
  }, [callers])

  return (
    <div className="sofa">
      <div className="sofa-head">
        <h2>{SOURCES.find(x => x.key === source)?.label} requests</h2>
        <div className="sofa-windows" role="tablist" aria-label="Source">
          {SOURCES.map(x => (
            <button key={x.key} type="button" role="tab" aria-selected={source === x.key}
                    className={`sofa-window${source === x.key ? ' active' : ''}`}
                    onClick={() => { setData(null); setSource(x.key) }}>{x.label}</button>
          ))}
        </div>
        <div className="sofa-windows" role="tablist" aria-label="Time window">
          {WINDOWS.map(w => (
            <button key={w.minutes} type="button" role="tab" aria-selected={minutes === w.minutes}
                    className={`sofa-window${minutes === w.minutes ? ' active' : ''}`}
                    onClick={() => setMinutes(w.minutes)}>{w.label}</button>
          ))}
        </div>
        {loadedAt ? <span className="sofa-updated">Updated {clock(loadedAt)} · refreshes every minute</span> : null}
      </div>
      {err ? <p className="admin-error">{err}</p> : null}
      {!data ? <p>Loading…</p> : (
        <>
          <StatusBanner data={data} />
          <Tiles data={data} minutes={minutes} />
          <section className="sofa-card">
            <h3>Requests per {data.bucket_minutes === 60 ? 'hour' : `${data.bucket_minutes} min`}</h3>
            <RateChart data={data} colourOf={colourOf} />
            <Legend callers={callers} colourOf={colourOf} />
          </section>
          <div className="sofa-grid">
            <section className="sofa-card">
              <h3>Who is asking</h3>
              <CallerTable callers={callers} minutes={minutes} budgets={data.budgets} colourOf={colourOf} />
            </section>
            <section className="sofa-card">
              <h3>What we asked for</h3>
              <PathTable summary={data.summary} />
            </section>
          </div>
          <section className="sofa-card">
            <h3>Blocks</h3>
            <Snapshots snaps={data.snapshots} />
          </section>
          <section className="sofa-card">
            <h3>Latest requests</h3>
            <RecentTable rows={data.recent} />
          </section>
        </>
      )}
    </div>
  )
}

function StatusBanner({ data }) {
  const ok = asDate(data.last?.ok?.t)
  const refused = asDate(data.last?.blocked?.t)
  const blockedFor = data.breaker?.blocked_for_s || 0
  const blocked = blockedFor > 0 || (refused && (!ok || refused > ok))
  if (blocked) {
    return (
      <div className="sofa-banner sofa-banner--blocked" role="status">
        <strong>Blocked.</strong>{' '}
        Last refused {refused ? `${dayClock(refused)} (${ago(refused)})` : '—'}.{' '}
        Last answered {ok ? `${dayClock(ok)} (${ago(ok)})` : 'not in the last two weeks'}.{' '}
        {blockedFor > 0 ? `Next attempt in ${span(blockedFor)}.` : 'Waiting for the next scheduled attempt.'}
      </div>
    )
  }
  return (
    <div className="sofa-banner sofa-banner--ok" role="status">
      <strong>Answering.</strong> Last answered {ok ? `${clock(ok)} (${ago(ok)})` : '—'}
      {refused ? `. Last refusal ${dayClock(refused)} (${ago(refused)}).` : '.'}
    </div>
  )
}

function Tiles({ data, minutes }) {
  const s = data.summary
  const refused = (s.by_status?.['403'] || 0) + (s.by_status?.['429'] || 0)
  const hourly = data.budgets?.hourly
  const perHour = s.per_hour
  const pct = hourly ? Math.min(100, (perHour / hourly) * 100) : 0
  const win = data.budgets?.window
  return (
    <div className="sofa-tiles">
      <div className="sofa-tile">
        <span className="sofa-tile-num">{s.requests.toLocaleString()}</span>
        <span className="sofa-tile-label">requests in {WINDOWS.find(w => w.minutes === minutes)?.label}</span>
      </div>
      <div className="sofa-tile">
        <span className="sofa-tile-num">{perHour.toLocaleString()}<small> / h</small></span>
        <span className="sofa-tile-label">average rate · {hourly ? `budget ${hourly}/h` : 'no known limit'}</span>
        {hourly ? <span className="sofa-meter"><span style={{ width: `${pct}%` }} className={pct >= 80 ? 'hot' : ''} /></span> : null}
      </div>
      <div className="sofa-tile">
        <span className={`sofa-tile-num${refused ? ' sofa-danger' : ''}`}>{refused}</span>
        <span className="sofa-tile-label">refused (403 / 429)</span>
      </div>
      {win ? (
        <div className="sofa-tile">
          <span className={`sofa-tile-num${s.busiest_window > win.limit ? ' sofa-danger' : ''}`}>{s.busiest_window}<small> / {win.limit}</small></span>
          <span className="sofa-tile-label">in the busiest {win.minutes} min · its limit</span>
        </div>
      ) : (
        <div className="sofa-tile">
          <span className="sofa-tile-num">{s.busiest_minute}</span>
          <span className="sofa-tile-label">in the busiest minute</span>
        </div>
      )}
    </div>
  )
}

/* Stacked bars, one per bucket, coloured by caller; a refusal is a red mark
   under its bar; the dashed line is the hourly budget scaled to the bar. */
function RateChart({ data, colourOf }) {
  const series = data.series || []
  const W = 960
  const H = 220
  const PAD = { l: 40, r: 8, t: 10, b: 34 }
  const budget = data.budgets?.hourly ? (data.budgets.hourly * data.bucket_minutes) / 60 : null
  const peak = Math.max(1, ...series.map(b => b.n), budget && data.bucket_minutes >= 5 ? budget : 0)
  const niceMax = (() => {
    const p = 10 ** Math.floor(Math.log10(peak))
    return [1, 2, 2.5, 5, 10].map(k => k * p).find(v => v >= peak)
  })()
  const plotW = W - PAD.l - PAD.r
  const plotH = H - PAD.t - PAD.b
  const bw = plotW / Math.max(1, series.length)
  const y = (v) => PAD.t + plotH - (v / niceMax) * plotH
  const ticks = [0, niceMax / 2, niceMax]
  const labelEvery = Math.max(1, Math.ceil(series.length / 8))
  return (
    <div className="sofa-chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="sofa-chart" role="img"
           aria-label="Requests per interval, by caller">
        {ticks.map(t => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="sofa-grid-line" />
            <text x={PAD.l - 6} y={y(t) + 4} className="sofa-axis" textAnchor="end">{Math.round(t)}</text>
          </g>
        ))}
        {series.map((b, i) => {
          let acc = 0
          const x = PAD.l + i * bw
          const when = new Date(b.t)
          return (
            <g key={b.t}>
              <title>{`${dayClock(when)} — ${b.n} request${b.n === 1 ? '' : 's'}${b.blocked ? `, ${b.blocked} refused` : ''}${b.failed ? `, ${b.failed} failed` : ''}\n`
                + Object.entries(b.by_caller).map(([c, n]) => `${c}: ${n}`).join('\n')}</title>
              <rect x={x} y={PAD.t} width={bw} height={plotH} fill="transparent" />
              {Object.entries(b.by_caller).sort((p, q) => q[1] - p[1]).map(([c, n]) => {
                const y0 = y(acc)
                acc += n
                return <rect key={c} x={x + bw * 0.1} width={Math.max(1, bw * 0.8)}
                             y={y(acc)} height={Math.max(0, y0 - y(acc))} fill={colourOf[c] || 'var(--ink-400)'} />
              })}
              {b.blocked ? <rect x={x} width={Math.max(2, bw)} y={H - PAD.b + 3} height={5} className="sofa-refused-mark" /> : null}
              {i % labelEvery === 0 ? (
                <text x={x + bw / 2} y={H - 8} className="sofa-axis" textAnchor="middle">
                  {data.bucket_minutes >= 60 ? when.toLocaleDateString([], { weekday: 'short', day: 'numeric' }) + ' ' + when.toLocaleTimeString([], { hour: 'numeric' }) : clock(when)}
                </text>
              ) : null}
            </g>
          )
        })}
        {budget && budget <= niceMax ? (
          <g>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(budget)} y2={y(budget)} className="sofa-budget-line" />
            <text x={W - PAD.r} y={y(budget) - 4} className="sofa-axis sofa-budget-label" textAnchor="end">budget</text>
          </g>
        ) : null}
      </svg>
    </div>
  )
}

function Legend({ callers, colourOf }) {
  if (!callers.length) return <p className="sofa-empty">No requests in this window.</p>
  return (
    <ul className="sofa-legend">
      {callers.map(([c]) => (
        <li key={c}><span className="sofa-swatch" style={{ background: colourOf[c] }} />{c}</li>
      ))}
      <li><span className="sofa-swatch sofa-refused-mark" />refused</li>
    </ul>
  )
}

function CallerTable({ callers, minutes, budgets, colourOf }) {
  if (!callers.length) return <p className="sofa-empty">Nothing asked.</p>
  return (
    <div className="admin-table-wrap">
      <table className="admin-table sofa-table">
        <thead><tr><th className="th-left">Caller</th><th>Requests</th><th>Per hour</th><th className="th-left">Of its budget</th></tr></thead>
        <tbody>
          {callers.map(([c, n]) => {
            const rate = Math.round((n * 60) / minutes)
            const budget = budgetFor(c, budgets)
            const pct = budget ? (rate / budget) * 100 : 0
            return (
              <tr key={c}>
                <td className="td-left"><span className="sofa-swatch" style={{ background: colourOf[c] }} />{c}</td>
                <td>{n.toLocaleString()}</td>
                <td>{rate}</td>
                <td className="td-left">
                  {budget ? (
                    <>
                      <span className="sofa-meter sofa-meter--row"><span style={{ width: `${Math.min(100, pct)}%` }} className={pct >= 80 ? 'hot' : ''} /></span>
                      <span className="sofa-meter-text">{Math.round(pct)}% of {budget}/h</span>
                    </>
                  ) : <span className="sofa-meter-text">no budget set</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function PathTable({ summary }) {
  const paths = Object.entries(summary.by_path || {})
  if (!paths.length) return <p className="sofa-empty">Nothing asked.</p>
  const max = Math.max(...paths.map(([, n]) => n))
  return (
    <div className="admin-table-wrap">
      <table className="admin-table sofa-table">
        <thead><tr><th className="th-left">Request</th><th className="th-left">Count</th></tr></thead>
        <tbody>
          {paths.map(([p, n]) => (
            <tr key={p}>
              <td className="td-left sofa-mono">{p}</td>
              <td className="td-left">
                <span className="sofa-meter sofa-meter--row"><span style={{ width: `${(n / max) * 100}%` }} /></span>
                <span className="sofa-meter-text">{n.toLocaleString()}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sofa-note">
        Answers: {Object.entries(summary.by_status || {}).map(([k, v]) => `${k === 'None' ? 'no answer' : k} × ${v}`).join(', ') || '—'}.
        Routes: {Object.entries(summary.routes || {}).map(([k, v]) => `${k} × ${v}`).join(', ') || '—'}.
      </p>
    </div>
  )
}

function Snapshots({ snaps }) {
  if (!snaps?.length) return <p className="sofa-empty">No blocks recorded.</p>
  return (
    <div className="admin-table-wrap">
      <table className="admin-table sofa-table">
        <thead><tr><th className="th-left">Blocked at</th><th className="th-left">Refused request</th><th>Hour before</th><th>6 h before</th><th>Busiest min</th><th className="th-left">Callers in the hour before</th></tr></thead>
        <tbody>
          {snaps.map(sn => {
            const at = snapshotTime(sn.file)
            return (
              <tr key={sn.file}>
                <td className="td-left td-nowrap">{at ? at.toLocaleString() : sn.file}</td>
                <td className="td-left sofa-mono">{sn.reason}</td>
                <td>{sn.requests_1h ?? '—'}</td>
                <td>{sn.requests_6h ?? '—'}</td>
                <td>{sn.busiest_minute ?? '—'}</td>
                <td className="td-left">{Object.entries(sn.by_caller_1h || {}).map(([c, n]) => `${c} ${n}`).join(', ') || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="sofa-note">Each block's full record — every request in the six hours before it — is kept on the server in /data/sofa-requests.</p>
    </div>
  )
}

function RecentTable({ rows }) {
  const list = [...(rows || [])].reverse()
  if (!list.length) return <p className="sofa-empty">No requests in this window.</p>
  return (
    <div className="admin-table-wrap sofa-recent">
      <table className="admin-table sofa-table">
        <thead><tr><th className="th-left">Time</th><th>Answer</th><th className="th-left">Caller</th><th className="th-left">Path</th><th>ms</th><th>Route</th></tr></thead>
        <tbody>
          {list.map((r, i) => (
            <tr key={`${r.t}-${i}`}>
              <td className="td-left td-nowrap">{dayClock(new Date(r.t))}</td>
              <td><span className={statusClass(r.status)}>{r.status ?? '—'}</span></td>
              <td className="td-left">{r.caller}</td>
              <td className="td-left sofa-mono">{r.path}</td>
              <td>{r.ms}</td>
              <td className="td-muted">{r.route}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
