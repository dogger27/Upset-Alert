import client from './client'

export const getPredictions = (tournamentId, userId) =>
  client.get(`/predictions/${tournamentId}`, { params: userId != null ? { user_id: userId } : {} }).then(r => r.data)

/* A DROPPED REPLY IS NOT A FAILED SAVE. On a weak phone connection the PUT
   reaches the server, the pick is stored, and the response never arrives —
   axios reports a timeout or a network error and the bracket used to snap
   back with "check your connection", having in fact saved. So when the
   failure carries no HTTP status (no reply at all, as opposed to a 403 or a
   500, which mean something), ask the server what it now holds: if it agrees
   with what we sent, the save happened and we return its answer. */
export const savePredictions = async (tournamentId, picks, userId) => {
  const params = userId != null ? { user_id: userId } : {}
  try {
    const r = await client.put(`/predictions/${tournamentId}`, { picks }, { params })
    return r.data
  } catch (err) {
    if (err?.response) throw err          // the server spoke; respect it
    const rows = await getPredictions(tournamentId, userId)   // may throw again
    const stored = new Map((rows || []).map(p => [String(p.match_id), p.predicted_winner_id]))
    const landed = Object.entries(picks).every(([matchId, winnerId]) =>
      winnerId == null
        ? !stored.has(String(matchId)) || stored.get(String(matchId)) == null
        : stored.get(String(matchId)) === winnerId)
    if (landed) return rows
    throw err
  }
}

export const getEntryStatus = () =>
  client.get('/predictions/entry-status').then(r => r.data)
