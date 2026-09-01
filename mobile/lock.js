/*
 * How long until picks close — and when to refuse to say.
 *
 * closing_time is a PREDICTION of day one's first ball. Under the original
 * rule the whole bracket shuts then, so a countdown is honest. Under
 * pick_lock_mode 'r1_progressive' picking closes when the first round is
 * COMPLETE, which depends on how the tennis goes and cannot be named in
 * advance — printing a time there promises something exact and wrong. The
 * website learned this and says nothing; so does this.
 */

export function lockLabel(t, now = Date.now()) {
  if (!t) return null
  if (t.is_locked) return { text: 'Picks closed', urgent: false }
  if (t.pick_lock_mode === 'r1_progressive') {
    return { text: 'Closes as round 1 finishes', urgent: false }
  }
  if (!t.closing_time) return null

  // SQLite hands these back without a zone; they are UTC.
  const at = new Date(t.closing_time.endsWith('Z') ? t.closing_time : t.closing_time + 'Z')
  const ms = at.getTime() - now
  if (Number.isNaN(ms)) return null
  if (ms <= 0) return { text: 'Picks closed', urgent: false }

  const mins = Math.floor(ms / 60000)
  const hrs = Math.floor(mins / 60)
  const days = Math.floor(hrs / 24)

  if (days >= 2) return { text: `Locks in ${days} days`, urgent: false }
  if (hrs >= 24) return { text: 'Locks tomorrow', urgent: false }
  if (hrs >= 1) return { text: `Locks in ${hrs}h ${mins % 60}m`, urgent: hrs < 6 }
  return { text: `Locks in ${mins}m`, urgent: true }
}
