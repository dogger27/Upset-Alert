/* THE SOFASCORE REQUEST LEDGER, ON THE PHONE (owner, 2026-09-26) — the web
   admin's Sofascore tab (frontend/src/pages/AdminSofascore.jsx) in native
   views. Whether we are blocked now, the rate against its budget, who is
   asking, and what we sent before each block. Reads
   /admin/sofascore-requests; sends nothing to Sofascore.

   The chart is plain Views, not SVG: react-native-svg is a native module,
   and adding one means a new build of the app for a page only admins see.

   Every source, one screen (owner, 2026-09-26): protennislive and Tennis
   Explorer are recorded the same way (backend services/request_ledger); the
   switch at the top picks which one /admin/requests reads. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native'
import { getSourceRequests } from '../../../../api'
import { useAuth } from '../../../../auth'
import { C, R, S, T } from '../../../../theme'
import { Muted, Screen } from '../../../../ui'

const SOURCES = [
  { key: 'sofascore', label: 'Sofascore' },
  { key: 'protennislive', label: 'PTL' },
  { key: 'tennisexplorer', label: 'TE' },
]
const WINDOWS = [
  { label: '1h', minutes: 60 },
  { label: '6h', minutes: 360 },
  { label: '24h', minutes: 1440 },
  { label: '7d', minutes: 10080 },
]
const COLOURS = [C.greenLit, C.clay, C.info, C.gold, C.h2hP2, C.faint]

const clock = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
const dayClock = (d) => d.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })
function ago(d) {
  if (!d) return 'never'
  const sec = Math.max(0, (Date.now() - d.getTime()) / 1000)
  if (sec < 90) return `${Math.round(sec)} s ago`
  if (sec < 5400) return `${Math.round(sec / 60)} min ago`
  if (sec < 172800) return `${(sec / 3600).toFixed(1)} h ago`
  return `${Math.round(sec / 86400)} days ago`
}
const span = (sec) => (sec < 5400 ? `${Math.round(sec / 60)} min` : `${(sec / 3600).toFixed(1)} h`)
const refused = (st) => st === 403 || st === 429
const answered = (st) => typeof st === 'number' && ((st >= 200 && st < 300) || st === 404)
function snapshotTime(file) {
  const m = /block-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z/.exec(file || '')
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])) : null
}

export default function SofascoreAdmin() {
  const { me } = useAuth()
  const [source, setSource] = useState('sofascore')
  const [minutes, setMinutes] = useState(1440)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await getSourceRequests(source, minutes, 50))
      setErr('')
    } catch (e) {
      setErr(e.message || 'Could not load the request ledger')
    }
  }, [source, minutes])
  useEffect(() => {
    load()
    const id = setInterval(load, 60000)
    return () => clearInterval(id)
  }, [load])

  const callers = useMemo(() => Object.entries(data?.summary?.by_caller || {}), [data])
  const colourOf = useMemo(() => {
    const m = {}
    callers.forEach(([c], i) => { m[c] = COLOURS[Math.min(i, COLOURS.length - 1)] })
    return m
  }, [callers])

  if (!me?.is_admin) return <Screen><Muted>This page is for admins.</Muted></Screen>

  return (
    <Screen onRefresh={load}>
      <View style={[s.windows, { marginBottom: S.sm }]} accessibilityRole="tablist">
        {SOURCES.map(x => (
          <Pressable key={x.key} onPress={() => { setData(null); setSource(x.key) }}
                     style={[s.window, source === x.key && s.windowOn]}
                     accessibilityRole="tab" accessibilityState={{ selected: source === x.key }}>
            <Text style={[s.windowText, source === x.key && s.windowTextOn]}>{x.label}</Text>
          </Pressable>
        ))}
      </View>
      <View style={s.windows} accessibilityRole="tablist">
        {WINDOWS.map(w => (
          <Pressable key={w.minutes} onPress={() => setMinutes(w.minutes)}
                     style={[s.window, minutes === w.minutes && s.windowOn]}
                     accessibilityRole="tab" accessibilityState={{ selected: minutes === w.minutes }}>
            <Text style={[s.windowText, minutes === w.minutes && s.windowTextOn]}>{w.label}</Text>
          </Pressable>
        ))}
      </View>
      {err ? <Text style={s.error}>{err}</Text> : null}
      {!data ? <Muted>Loading</Muted> : (
        <View style={{ gap: S.md }}>
          <Banner data={data} />
          <Tiles data={data} />
          <View style={s.card}>
            <Text style={s.h}>Requests per {data.bucket_minutes === 60 ? 'hour' : `${data.bucket_minutes} min`}</Text>
            <Chart data={data} colourOf={colourOf} />
            <View style={s.legend}>
              {callers.map(([c]) => (
                <View key={c} style={s.legendItem}>
                  <View style={[s.swatch, { backgroundColor: colourOf[c] }]} />
                  <Text style={s.legendText}>{c}</Text>
                </View>
              ))}
              <View style={s.legendItem}>
                <View style={[s.swatch, { backgroundColor: C.bad }]} />
                <Text style={s.legendText}>refused</Text>
              </View>
            </View>
          </View>
          <View style={s.card}>
            <Text style={s.h}>Who is asking</Text>
            {callers.length ? callers.map(([c, n]) => {
              const rate = Math.round((n * 60) / minutes)
              const budget = data.budgets?.callers?.[c.split('.')[0]] ?? data.budgets?.caller_default
              const pct = budget ? (rate / budget) * 100 : 0
              return (
                <View key={c} style={s.callerRow}>
                  <View style={s.callerHead}>
                    <View style={[s.swatch, { backgroundColor: colourOf[c] }]} />
                    <Text style={s.callerName}>{c}</Text>
                    <Text style={s.callerNum}>{n.toLocaleString()}</Text>
                  </View>
                  {budget ? (
                    <View style={s.meter}>
                      <View style={[s.meterFill, { width: `${Math.min(100, pct)}%` }, pct >= 80 && s.meterHot]} />
                    </View>
                  ) : null}
                  <Text style={s.meterText}>{budget ? `${rate}/h, ${Math.round(pct)}% of its ${budget}/h budget` : `${rate}/h`}</Text>
                </View>
              )
            }) : <Muted>Nothing asked in this window.</Muted>}
          </View>
          <View style={s.card}>
            <Text style={s.h}>What we asked for</Text>
            {Object.entries(data.summary.by_path || {}).map(([p, n]) => (
              <View key={p} style={s.pathRow}>
                <Text style={s.mono}>{p}</Text>
                <Text style={s.callerNum}>{n.toLocaleString()}</Text>
              </View>
            ))}
            <Text style={s.note}>
              Answers: {Object.entries(data.summary.by_status || {}).map(([k, v]) => `${k === 'None' ? 'no answer' : k} × ${v}`).join(', ') || 'none'}
            </Text>
          </View>
          <View style={s.card}>
            <Text style={s.h}>Blocks</Text>
            {data.snapshots?.length ? data.snapshots.map(sn => {
              const at = snapshotTime(sn.file)
              return (
                <View key={sn.file} style={s.snap}>
                  <Text style={s.snapWhen}>{at ? at.toLocaleString() : sn.file}</Text>
                  <Text style={s.mono}>{sn.reason}</Text>
                  <Text style={s.note}>
                    {sn.requests_1h ?? 0} requests in the hour before ({sn.requests_6h ?? 0} in six), busiest minute {sn.busiest_minute ?? 0}
                  </Text>
                  <Text style={s.note}>
                    {Object.entries(sn.by_caller_1h || {}).map(([c, n]) => `${c} ${n}`).join(', ')}
                  </Text>
                </View>
              )
            }) : <Muted>No blocks recorded.</Muted>}
          </View>
          <View style={s.card}>
            <Text style={s.h}>Latest requests</Text>
            {[...(data.recent || [])].reverse().map((r, i) => (
              <View key={`${r.t}-${i}`} style={s.reqRow}>
                <View style={[s.pill, refused(r.status) ? s.pillBad : answered(r.status) ? s.pillOk : s.pillOther]}>
                  <Text style={[s.pillText, { color: refused(r.status) ? C.bad : answered(r.status) ? C.ok : C.muted }]}>
                    {r.status ?? 'none'}
                  </Text>
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={s.mono}>{r.path}</Text>
                  <Text style={s.note}>{dayClock(new Date(r.t))}, {r.caller}, {r.ms} ms</Text>
                </View>
              </View>
            ))}
            {!data.recent?.length ? <Muted>No requests in this window.</Muted> : null}
          </View>
        </View>
      )}
    </Screen>
  )
}

function Banner({ data }) {
  const ok = data.last?.ok?.t ? new Date(data.last.ok.t) : null
  const no = data.last?.blocked?.t ? new Date(data.last.blocked.t) : null
  const waitS = data.breaker?.blocked_for_s || 0
  const blocked = waitS > 0 || (no && (!ok || no > ok))
  return (
    <View style={[s.banner, blocked ? s.bannerBad : s.bannerOk]} accessibilityRole="summary">
      <Text style={[s.bannerHead, { color: blocked ? C.bad : C.ok }]}>{blocked ? 'Blocked' : 'Answering'}</Text>
      {blocked ? (
        <>
          <Text style={s.bannerText}>Last refused {no ? `${dayClock(no)} (${ago(no)})` : 'never'}</Text>
          <Text style={s.bannerText}>Last answered {ok ? `${dayClock(ok)} (${ago(ok)})` : 'not in the last two weeks'}</Text>
          <Text style={s.bannerText}>{waitS > 0 ? `Next attempt in ${span(waitS)}` : 'Waiting for the next scheduled attempt'}</Text>
        </>
      ) : (
        <Text style={s.bannerText}>Last answered {ok ? `${clock(ok)} (${ago(ok)})` : 'never'}
          {no ? `. Last refusal ${dayClock(no)} (${ago(no)})` : ''}</Text>
      )}
    </View>
  )
}

function Tiles({ data }) {
  const sm = data.summary
  const no = (sm.by_status?.['403'] || 0) + (sm.by_status?.['429'] || 0)
  const hourly = data.budgets?.hourly
  const pct = hourly ? Math.min(100, (sm.per_hour / hourly) * 100) : 0
  const win = data.budgets?.window
  return (
    <View style={s.tiles}>
      <View style={s.tile}>
        <Text style={s.tileNum}>{sm.requests.toLocaleString()}</Text>
        <Text style={s.tileLabel}>requests</Text>
      </View>
      <View style={s.tile}>
        <Text style={s.tileNum}>{sm.per_hour}<Text style={s.tileUnit}> /h</Text></Text>
        <Text style={s.tileLabel}>{hourly ? `budget ${hourly}/h` : 'no known limit'}</Text>
        {hourly ? <View style={s.meter}><View style={[s.meterFill, { width: `${pct}%` }, pct >= 80 && s.meterHot]} /></View> : null}
      </View>
      <View style={s.tile}>
        <Text style={[s.tileNum, no > 0 && { color: C.bad }]}>{no}</Text>
        <Text style={s.tileLabel}>refused</Text>
      </View>
      {win ? (
        <View style={s.tile}>
          <Text style={[s.tileNum, sm.busiest_window > win.limit && { color: C.bad }]}>{sm.busiest_window}<Text style={s.tileUnit}> /{win.limit}</Text></Text>
          <Text style={s.tileLabel}>busiest {win.minutes} min, its limit</Text>
        </View>
      ) : (
        <View style={s.tile}>
          <Text style={s.tileNum}>{sm.busiest_minute}</Text>
          <Text style={s.tileLabel}>busiest minute</Text>
        </View>
      )}
    </View>
  )
}

/* Stacked bars by caller, a red mark under any bucket with a refusal, and
   the hourly budget scaled to one bucket as a line. */
const CHART_H = 140
function Chart({ data, colourOf }) {
  const series = data.series || []
  const budget = data.budgets?.hourly ? (data.budgets.hourly * data.bucket_minutes) / 60 : null
  const peak = Math.max(1, ...series.map(b => b.n), budget && data.bucket_minutes >= 5 ? budget : 0)
  const first = series[0] ? new Date(series[0].t) : null
  const last = series.length ? new Date(series[series.length - 1].t) : null
  const label = (d) => (data.bucket_minutes >= 60
    ? d.toLocaleDateString([], { weekday: 'short', day: 'numeric' }) : clock(d))
  return (
    <View>
      <View style={s.chartRow}>
        <View style={s.yAxis}>
          <Text style={s.axis}>{Math.round(peak)}</Text>
          <Text style={s.axis}>0</Text>
        </View>
        <View style={s.plot}>
          <View style={s.bars}>
            {series.map(b => (
              <View key={b.t} style={s.barCol}>
                {Object.entries(b.by_caller).sort((p, q) => q[1] - p[1]).map(([c, n]) => (
                  <View key={c} style={{ height: (n / peak) * CHART_H, backgroundColor: colourOf[c] || C.faint }} />
                ))}
              </View>
            ))}
          </View>
          {budget && budget <= peak ? (
            <View style={[s.budgetLine, { bottom: (budget / peak) * CHART_H }]}>
              <Text style={s.budgetText}>budget</Text>
            </View>
          ) : null}
          <View style={s.marks}>
            {series.map(b => <View key={b.t} style={[s.markCol, b.blocked > 0 && { backgroundColor: C.bad }]} />)}
          </View>
        </View>
      </View>
      {first ? (
        <View style={s.xAxis}>
          <Text style={s.axis}>{label(first)}</Text>
          <Text style={s.axis}>{label(last)}</Text>
        </View>
      ) : null}
    </View>
  )
}

const s = StyleSheet.create({
  windows: { flexDirection: 'row', borderWidth: 1, borderColor: C.borderOn, borderRadius: R.pill, overflow: 'hidden', marginBottom: S.md },
  window: { flex: 1, paddingVertical: S.sm, alignItems: 'center' },
  windowOn: { backgroundColor: C.green },
  windowText: { ...T.smallMed, color: C.muted },
  windowTextOn: { color: C.ink, fontFamily: 'Archivo_700Bold' },
  error: { ...T.small, color: C.bad, marginBottom: S.sm },

  banner: { borderRadius: R.md, borderWidth: 1, padding: S.md, gap: 2 },
  bannerBad: { backgroundColor: '#2a1414', borderColor: '#5c2626' },
  bannerOk: { backgroundColor: C.greenDeep, borderColor: C.green },
  bannerHead: { ...T.h2 },
  bannerText: { ...T.small, color: C.inkBody },

  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: S.sm },
  tile: { flexGrow: 1, flexBasis: '45%', backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderRadius: R.md, padding: S.md },
  tileNum: { ...T.h1, color: C.ink, fontVariant: ['tabular-nums'] },
  tileUnit: { ...T.small, color: C.muted },
  tileLabel: { ...T.tiny, color: C.faint },

  card: { backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderRadius: R.md, padding: S.md, gap: S.sm },
  h: { ...T.bodyBold, color: C.ink },

  chartRow: { flexDirection: 'row', gap: 4 },
  yAxis: { height: CHART_H, justifyContent: 'space-between', alignItems: 'flex-end', width: 28 },
  plot: { flex: 1 },
  bars: { height: CHART_H, flexDirection: 'row', alignItems: 'flex-end', borderBottomWidth: 1, borderBottomColor: C.borderOn },
  barCol: { flex: 1, marginHorizontal: 0.5, flexDirection: 'column-reverse', overflow: 'hidden' },
  budgetLine: { position: 'absolute', left: 0, right: 0, borderTopWidth: 1, borderColor: C.bad, borderStyle: 'dashed' },
  budgetText: { ...T.tiny, color: C.bad, position: 'absolute', right: 0, top: -15 },
  marks: { flexDirection: 'row', height: 4, marginTop: 2 },
  markCol: { flex: 1, marginHorizontal: 0.5 },
  xAxis: { flexDirection: 'row', justifyContent: 'space-between', marginLeft: 32, marginTop: 2 },
  axis: { ...T.tiny, color: C.faint, fontVariant: ['tabular-nums'] },

  legend: { flexDirection: 'row', flexWrap: 'wrap', gap: S.sm },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  legendText: { ...T.tiny, color: C.muted },
  swatch: { width: 10, height: 10, borderRadius: 2 },

  callerRow: { gap: 3, paddingVertical: 4 },
  callerHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  callerName: { ...T.smallMed, color: C.inkBody, flex: 1 },
  callerNum: { ...T.smallBold, color: C.ink, fontVariant: ['tabular-nums'] },
  meter: { height: 6, backgroundColor: C.sunken, borderRadius: 3, overflow: 'hidden', marginTop: 4 },
  meterFill: { height: '100%', backgroundColor: C.greenLit, borderRadius: 3 },
  meterHot: { backgroundColor: C.bad },
  meterText: { ...T.tiny, color: C.faint },

  pathRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm, paddingVertical: 3, borderTopWidth: 1, borderTopColor: C.border },
  mono: { ...T.tiny, color: C.inkBody, flex: 1, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  note: { ...T.tiny, color: C.faint },

  snap: { gap: 2, paddingVertical: S.xs, borderTopWidth: 1, borderTopColor: C.border },
  snapWhen: { ...T.smallBold, color: C.ink },

  reqRow: { flexDirection: 'row', alignItems: 'center', gap: S.sm, paddingVertical: 4, borderTopWidth: 1, borderTopColor: C.border },
  pill: { minWidth: 44, paddingHorizontal: 6, paddingVertical: 2, borderRadius: R.pill, alignItems: 'center' },
  pillOk: { backgroundColor: C.greenDeep },
  pillBad: { backgroundColor: '#2a1414' },
  pillOther: { backgroundColor: C.sunken },
  pillText: { ...T.tiny, fontFamily: 'Archivo_700Bold' },
})
