/*
 * How long until picks close.
 *
 * closing_time is a PREDICTION of day one's first ball, and EVERY draw counts
 * down to it — including a match-by-match one (owner, 2026-09-19, correcting
 * the earlier reading in this file).
 *
 * The old reasoning here was that a 'r1_progressive' draw closes when the
 * first round is COMPLETE, an hour nobody can name in advance, so it should
 * name none. That describes the last pick to freeze rather than the first.
 * Locking under that mode STARTS at the first ball: the match going on court
 * freezes, and so does every match downstream of it
 * (services/locking._locked_with_downstream), which is most of a bracket by
 * the end of the round. A reader who wants to finish their picks has until the
 * first ball in either mode, and that is the deadline this line is for.
 *
 * Residual edits — a later-round match whose path is still untouched — remain
 * possible through round one under that mode. They are the exception, they are
 * what the draw screen's own refusals explain match by match, and they are not
 * what a card on the dashboard is counting down to.
 */

/* A LABEL AND A VALUE, so the card can set the value loud and the label quiet:
   the value is the part you can miss. The old wording ran the unit after the
   number as a suffix ("52 hrs until lock"), which read as a caption on the
   number rather than a statement about the draw. */
const mk = (label, value, urgent = false) =>
  ({ label, value, text: `${label} ${value}`.trim(), urgent })

export function lockLabel(t, now = Date.now()) {
  if (!t) return null
  if (t.is_locked) return mk('Picks', 'closed')
  if (!t.closing_time) return null

  // SQLite hands these back without a zone; they are UTC.
  const at = new Date(t.closing_time.endsWith('Z') ? t.closing_time : t.closing_time + 'Z')
  const ms = at.getTime() - now
  if (Number.isNaN(ms)) return null
  if (ms <= 0) {
    /* THE COUNTDOWN IS SPENT. Under the original rule that is simply the end
       of it. Under match-by-match the draw is not `is_locked` until the first
       round COMPLETES, so this is the one window where a card would otherwise
       claim picks were closed for the two days a first round takes — while the
       draw screen still accepts changes to untouched later rounds. It says
       where the closing has got to instead. */
    return t.pick_lock_mode === 'r1_progressive'
      ? mk('Lock at:', 'End of R1')
      : mk('Picks', 'closed')
  }

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
   cannot be named in advance.

   `hidden` IS THE SERVER'S OWN predictions_hidden, AND IT DECIDES. This
   function used to answer null for any active draw, on the assumption that a
   draw going active makes picks visible. It does not: under match-by-match
   locking a draw goes active at the first ball and picks stay withheld until
   every first-round match has started, a day or two later. For that window the
   standings said nothing at all while the server was still withholding the
   columns — the same root cause as the predictors sheet reading "No one."
   (owner, 2026-09-21). Pass the flag wherever the payload carries it; the
   status guess below remains for the screens that read the tournaments LIST,
   which does not. */
export function othersPicksNote(t, hidden = null) {
  if (!t) return null
  if (hidden === true) return t.pick_lock_mode === 'r1_progressive'
    ? 'Members’ picks open once every first-round match has started.'
    : 'Members’ picks open after pick selection closes.'
  if (hidden === false) return null
  if (t.status === 'active' || t.status === 'completed') return null
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


/* WHY A MATCH CAN HAVE NO PREDICTORS AND STILL HAVE BEEN PREDICTED.
 *
 * The predictors endpoint answers empty columns in two situations that mean
 * opposite things: nobody picked this match, or everybody did and the server
 * is still withholding it. It distinguishes them itself with `hidden`, and
 * the sheet did not look — so a completed first-round match at Singapore read
 * "Right (0) — No one." while six people had picked it, one of them
 * correctly (owner, 2026-09-21).
 *
 * `hidden` can only mean match-by-match locking on an unfinished draw:
 * services/locking.predictions_visible() returns true at once for a completed
 * draw and for every other lock mode, so one sentence covers every case that
 * reaches here. It is deliberately the SAME rule othersPicksNote states on
 * the standings, worded for a sheet about one match.
 */
export const HIDDEN_PICKS_NOTE =
  'Picks are hidden while they can still change. '
  + 'They open once every first-round match has started.'


/* The sentence to show INSTEAD OF the two columns, or null to show them.
 *
 * Returns null for a payload that has not arrived: nothing loaded is not an
 * answer, and the caller is already drawing a spinner for it.
 */
export function predictorsMessage(d) {
  if (!d) return null
  return d.hidden ? HIDDEN_PICKS_NOTE : null
}
