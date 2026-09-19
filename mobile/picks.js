/*
 * MAKING A PICK — the arithmetic, with no React in it.
 *
 * Ported from frontend/src/pages/TournamentDraw.jsx (computeNextPicks,
 * projectPicks, blockedByLive), which is itself written against what the
 * server does on save (predictions.py + services/highest_rank_bot.py). All
 * three have to agree: a bracket that shows one thing, sends another and is
 * stored as a third is the failure this file exists to prevent.
 *
 * A pick set is a plain object, `{[matchId]: drawEntryId}` — the shape the PUT
 * body takes, so nothing has to be converted on the way out. Object keys are
 * strings in JavaScript whatever you put in, so every lookup here goes through
 * a match's own `id` and every comparison of a match id uses Number().
 *
 * THE THREE RULES, and why each exists:
 *
 * 1. CASCADE-CLEAR (computeNextPicks). Moving a winner tears down the path the
 *    old player was carrying: every later match where they were picked to
 *    appear no longer makes sense. Those picks are cleared, up the tree, or the
 *    server keeps a pick for somebody who can no longer get there.
 *
 * 2. NOTHING IS EVER BLANK (projectPicks). Whatever the user has not chosen
 *    takes the better-ranked player — the same projection the Highest_Rank
 *    account plays and the same one the server applies on every save. Run here
 *    too, because waiting for the round trip to tell us meant the bracket
 *    showed either a gap or the player who had just been knocked out.
 *
 * 3. A PICK THAT DISTURBS A MATCH IN PLAY IS REFUSED WHOLE (blockedByLive).
 *    The server refuses those writes and is right to. Asked here first, before
 *    anything moves, so the screen never shows a state the server rejected.
 */

/* The server's _rank_key, in three fields that are already on every draw
   entry: the ranking, then the seed, then the id as a tiebreak. NOT the
   seeding badge, which is draw order — reading that instead would disagree
   with the server on exactly the matches people notice. */
function rankKey(entry, id) {
  return [entry?.ranking ?? Infinity, entry?.seed ?? Infinity, id ?? Infinity]
}

function betterOf(a, b, entryById) {
  if (a == null) return b ?? null
  if (b == null) return a
  const ka = rankKey(entryById[a], a)
  const kb = rankKey(entryById[b], b)
  for (let i = 0; i < 3; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? a : b
  return a
}

function indexByKey(matches) {
  const byKey = {}
  for (const m of matches || []) byKey[`${m.round_number}:${m.match_number}`] = m
  return byKey
}

/* Rule 1. The clicked match takes the new player; every match downstream that
   was holding the OLD one is cleared to null. Null is meaningful — the server
   deletes that row — so it is written rather than the key being dropped. */
export function computeNextPicks(basePicks, matchId, playerId, matches) {
  const next = { ...basePicks }
  const old = next[matchId] ?? null
  if (old != null && old !== playerId) {
    const byKey = indexByKey(matches)
    let cur = (matches || []).find(m => Number(m.id) === Number(matchId))
    while (cur) {
      const up = byKey[`${cur.round_number + 1}:${Math.ceil(cur.match_number / 2)}`]
      if (!up) break
      if (next[up.id] === old) next[up.id] = null
      cur = up
    }
  }
  next[matchId] = playerId
  return next
}

/* Rule 2. Walk the draw forward filling every match: the user's own choice
   wherever it is one of the two players actually in front of them, else the
   better-ranked of the pair.

   THIS IS WHAT IS SHOWN, NOT WHAT IS SENT. The payload stays un-projected —
   the user's own picks and nothing else — because the server fills the blanks
   itself and a projection posted back would turn a guess the app made into a
   choice the user appears to have made. So a pick for a player who can no
   longer reach a match is passed over here for advancing, while the stored
   pick is left exactly as the user made it.

   A bye is not a contest: whoever is there goes through, and the bye match
   itself is never given a pick (feedback_bye_opponent_clickable). */
export function projectPicks(basePicks, matches, entries) {
  if (!matches || !matches.length) return basePicks
  const entryById = {}
  for (const e of entries || []) entryById[e.id] = e
  const out = { ...basePicks }
  const winnerOf = {}
  const rounds = [...new Set(matches.map(m => m.round_number))].sort((x, y) => x - y)
  const first = rounds[0]
  for (const r of rounds) {
    for (const m of matches.filter(x => x.round_number === r)) {
      let a, b
      if (r === first) {
        a = m.player1?.id ?? null
        b = m.player2?.id ?? null
      } else {
        a = winnerOf[`${r - 1}:${m.match_number * 2 - 1}`] ?? null
        b = winnerOf[`${r - 1}:${m.match_number * 2}`] ?? null
      }
      const chosen = out[m.id] ?? null
      const valid = chosen != null && (chosen === a || chosen === b)
      const win = m.is_bye ? (a ?? b) : (valid ? chosen : betterOf(a, b, entryById))
      winnerOf[`${r}:${m.match_number}`] = win ?? null
      if (!m.is_bye && win != null) out[m.id] = win
    }
  }
  return out
}

/* Rule 3. The same question the server asks (locking.rejected_changes), asked
   early enough to be useful: does this change touch a frozen match? Only a
   CHANGE counts — the client posts its whole set every time, so an unchanged
   pick on a match now in play must still be allowed through. */
export function blockedByLive(basePicks, nextPicks, lockedIds) {
  if (!lockedIds || !lockedIds.size) return false
  return Object.keys(nextPicks).some(mid => (
    (nextPicks[mid] ?? null) !== (basePicks[mid] ?? null) && lockedIds.has(Number(mid))
  ))
}

/* The rows the server returns, as a pick set. Null winners are dropped: the
   row is gone server-side, and an absent key and a null value mean the same
   thing to everything above. */
export function picksFromRows(rows) {
  const out = {}
  for (const p of rows || []) if (p.predicted_winner_id != null) out[p.match_id] = p.predicted_winner_id
  return out
}

/* What buildBracket wants: a Map keyed on the match id as a NUMBER, since that
   is what it looks up with. */
export function picksMap(picks) {
  const m = new Map()
  for (const [k, v] of Object.entries(picks || {})) m.set(Number(k), v ?? null)
  return m
}

/* Whether this pick set names a champion — a pick on a match in the last
   round that holds one. What the tiebreak questions wait for: they are about
   a final between two players, so there is no point asking before the bracket
   says who they are. */
export function namesChampion(picks, matches) {
  const last = Math.max(0, ...(matches || []).map(m => m.round_number))
  return (matches || []).some(m => (
    m.round_number === last && !m.is_bye && (picks?.[m.id] ?? null) != null
  ))
}
