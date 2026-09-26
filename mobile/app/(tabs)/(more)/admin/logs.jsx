/* THE SYSTEM LOG, ON THE PHONE (owner, 2026-09-26) — the web admin's Logs tab,
   read-only: one row per problem (the server groups them with the same
   fingerprint the alert emails use), newest first, tap for its occurrences. */
import { useCallback, useEffect, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { getAdminLogs } from '../../../../api'
import { useAuth } from '../../../../auth'
import { C, R, S, T } from '../../../../theme'
import { Muted, Screen } from '../../../../ui'

const LEVELS = [
  { key: '', label: 'All' },
  { key: 'error', label: 'Errors' },
  { key: 'warning', label: 'Warnings' },
  { key: 'info', label: 'Info' },
]
const TONE = { error: C.bad, warning: C.warn, info: C.info }

const when = (iso) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '')

export default function AdminLogs() {
  const { me } = useAuth()
  const [level, setLevel] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)

  const load = useCallback(async () => {
    try {
      setData(await getAdminLogs(level))
      setErr('')
    } catch (e) {
      setErr(e.message || 'Could not load the log')
    }
  }, [level])
  useEffect(() => { setData(null); load() }, [load])

  if (!me?.is_admin) return <Screen><Muted>This page is for admins.</Muted></Screen>

  return (
    <Screen onRefresh={load}>
      <View style={s.levels} accessibilityRole="tablist">
        {LEVELS.map(l => (
          <Pressable key={l.key} onPress={() => setLevel(l.key)}
                     style={[s.level, level === l.key && s.levelOn]}
                     accessibilityRole="tab" accessibilityState={{ selected: level === l.key }}>
            <Text style={[s.levelText, level === l.key && s.levelTextOn]}>{l.label}</Text>
          </Pressable>
        ))}
      </View>
      {err ? <Text style={s.error}>{err}</Text> : null}
      {!data ? <Muted>Loading</Muted> : !data.groups?.length ? <Muted>Nothing logged.</Muted> : (
        <View style={{ gap: S.sm }}>
          {data.groups.map(g => {
            const shown = open === g.fingerprint
            return (
              <Pressable key={g.fingerprint} onPress={() => setOpen(shown ? null : g.fingerprint)}
                         style={({ pressed }) => [s.row, { borderLeftColor: TONE[g.level] || C.faint }, pressed && { opacity: 0.8 }]}
                         accessibilityRole="button" accessibilityState={{ expanded: shown }}>
                <View style={s.rowHead}>
                  <Text style={[s.levelTag, { color: TONE[g.level] || C.faint }]}>{g.level}</Text>
                  {g.count > 1 ? <Text style={s.count}>×{g.count}</Text> : null}
                  <Text style={[s.time, s.timeEnd]}>{when(g.last_seen)}</Text>
                </View>
                {/* Its own line: squeezed into the head row, "schedule_shadow"
                    broke mid-word (owner, 2026-09-26). */}
                <Text style={s.cat}>{g.category}</Text>
                <Text style={s.msg}>{g.message}</Text>
                {shown ? (
                  <View style={s.occ}>
                    {g.count > 1 ? <Text style={s.time}>First seen {when(g.first_seen)}</Text> : null}
                    {g.occurrences.slice(0, 10).map(o => (
                      <View key={o.id} style={s.occRow}>
                        <Text style={s.time}>{when(o.created_at)}</Text>
                        {o.message !== g.message ? <Text style={s.occMsg}>{o.message}</Text> : null}
                        {o.detail ? (
                          <Text style={s.detail}>
                            {typeof o.detail === 'string' ? o.detail : JSON.stringify(o.detail, null, 1)}
                          </Text>
                        ) : null}
                      </View>
                    ))}
                  </View>
                ) : null}
              </Pressable>
            )
          })}
        </View>
      )}
    </Screen>
  )
}

const s = StyleSheet.create({
  levels: { flexDirection: 'row', borderWidth: 1, borderColor: C.borderOn, borderRadius: R.pill, overflow: 'hidden', marginBottom: S.md },
  level: { flex: 1, paddingVertical: S.sm, alignItems: 'center' },
  levelOn: { backgroundColor: C.green },
  levelText: { ...T.smallMed, color: C.muted },
  levelTextOn: { color: C.ink, fontFamily: 'Archivo_700Bold' },
  error: { ...T.small, color: C.bad, marginBottom: S.sm },
  row: { backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderLeftWidth: 3, borderRadius: R.sm, padding: S.md, gap: 4 },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: S.sm },
  levelTag: { ...T.tiny, fontFamily: 'Archivo_700Bold', textTransform: 'uppercase', letterSpacing: 0.6 },
  cat: { ...T.tiny, color: C.muted },
  timeEnd: { marginLeft: 'auto' },
  count: { ...T.tiny, color: C.ink, fontFamily: 'Archivo_700Bold' },
  time: { ...T.tiny, color: C.faint },
  msg: { ...T.small, color: C.inkBody },
  occ: { gap: S.sm, marginTop: S.xs, paddingTop: S.sm, borderTopWidth: 1, borderTopColor: C.border },
  occRow: { gap: 2 },
  occMsg: { ...T.tiny, color: C.inkBody },
  detail: { ...T.tiny, color: C.muted },
})
