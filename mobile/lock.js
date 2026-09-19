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

/* TWO DIFFERENT SENTENCES, BECAUSE THEY ARE TWO DIFFERENT FACTS (owner,
   2026-09-19). A draw on the original rule locks at a MOMENT, so it gets
   "Locks in: 52 hrs" — a quantity that counts down. A match-by-match draw
   locks at an EVENT nobody can time, so it gets "Lock at: End of R1" — a
   place in the tournament, not a clock. The old wording ran the unit after
   the number as a suffix ("52 hrs until lock"), which read as a caption on
   the number rather than a statement about the draw.

   A LABEL AND A VALUE, so the card can set the value loud and the label
   quiet: the value is the part you can miss. */
const mk = (label, value, urgent = false) =>
  ({ label, value, text: `${label} ${value}`.trim(), urgent })

export function lockLabel(t, now = Date.now()) {
  if (!t) return null
  if (t.is_locked) return mk('Picks', 'closed')
  if (t.pick_lock_mode === 'r1_progressive') {
    /* NO CLOCK, on purpose — see the note at the top of the file. The first
       round finishes when the tennis says so, and naming an hour for it would
       promise something exact and wrong. */
    return mk('Lock at:', 'End of R1')
  }
  if (!t.closing_time) return null

  // SQLite hands these back without a zone; they are UTC.
  const at = new Date(t.closing_time.endsWith('Z') ? t.closing_time : t.closing_time + 'Z')
  const ms = at.getTime() - now
  if (Number.isNaN(ms)) return null
  if (ms <= 0) return mk('Picks', 'closed')

  const mins = Math.floor(ms / 60000)
  const hrs = Math.floor(mins / 60)
  const days = Math.floor(hrs / 24)

  /* HOURS RIGHT OUT TO THREE DAYS, where this used to switch to days at one
     (owner's own example was "52 hrs"). Two days out, "52 hrs" is both the
     more precise reading and the more urgent one, which is what this line is
     for; past that the number stops meaning anything and days take over. */
  if (hrs >= 72) return mk('Locks in:', `${days} days`)
  if (hrs >= 24) return mk('Locks in:', `${hrs} hrs`)
  if (hrs >= 1) return mk('Locks in:', `${hrs}h ${mins % 60}m`, hrs < 6)
  return mk('Locks in:', `${mins}m`, true)
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
