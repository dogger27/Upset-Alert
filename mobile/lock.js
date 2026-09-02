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
  if (t.is_locked) return { value: 'Closed', suffix: '', text: 'Picks closed', urgent: false }
  if (t.pick_lock_mode === 'r1_progressive') {
    // No number, on purpose — see above. The suffix carries the whole meaning.
    return { value: 'R1', suffix: 'closes as round 1 finishes', text: 'Closes as round 1 finishes', urgent: false }
  }
  if (!t.closing_time) return null

  // SQLite hands these back without a zone; they are UTC.
  const at = new Date(t.closing_time.endsWith('Z') ? t.closing_time : t.closing_time + 'Z')
  const ms = at.getTime() - now
  if (Number.isNaN(ms)) return null
  if (ms <= 0) return { value: 'Closed', suffix: '', text: 'Picks closed', urgent: false }

  const mins = Math.floor(ms / 60000)
  const hrs = Math.floor(mins / 60)
  const days = Math.floor(hrs / 24)

  // Split so the card can set the NUMBER large and the unit small — the number
  // is the thing you can miss, and it should be the loudest thing on the card.
  const mk = (value, suffix, urgent = false) =>
    ({ value, suffix, text: `${value} ${suffix}`.trim(), urgent })

  if (days >= 2) return mk(String(days), 'days to lock')
  if (hrs >= 24) return mk('1', 'day to lock')
  if (hrs >= 1) return mk(`${hrs}h ${mins % 60}m`, 'to lock', hrs < 6)
  return mk(`${mins}m`, 'to lock', true)
}


/* WHEN ANOTHER MEMBER'S PICKS CAN BE SEEN — the site's sidebar toast, and the
   server's predictions_visible, in one sentence.

   Under the original rule nothing can change after the first ball, so the
   server never hides a bracket: the only wait is for picking to close, and
   that is a time the sheet can name. Under match-by-match ("r1_progressive"
   in the admin panel) picks stay editable through round one, so a visible
   bracket is a bracket to copy: the server withholds it until EVERY
   first-round match has started — an hour that depends on the tennis and
   cannot be named in advance. Null once the draw is active or finished. */
export function othersPicksNote(t) {
  if (!t || t.status === 'active' || t.status === 'completed') return null
  if (t.pick_lock_mode === 'r1_progressive') {
    return 'Members’ picks open once every first-round match has started.'
  }
  if (!t.closing_time) return 'Members’ picks open after pick selection closes.'
  const at = new Date(t.closing_time.endsWith('Z') ? t.closing_time : t.closing_time + 'Z')
  const when = Number.isNaN(at.getTime()) ? '' : at.toLocaleString([], {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  })
  return `Members’ picks open after pick selection closes${when ? `: ${when}` : ''}.`
}
