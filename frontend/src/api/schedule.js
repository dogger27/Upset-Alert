import client from './client'

export async function getScheduleDay({ date, tournamentId }) {
  const params = {}
  if (date) params.play_date = date
  if (tournamentId) params.tournament_id = tournamentId
  const { data } = await client.get('/schedule/day', { params })
  return data
}

export async function getScheduleDates(tournamentId) {
  const params = {}
  if (tournamentId) params.tournament_id = tournamentId
  const { data } = await client.get('/schedule/dates', { params })
  return data
}

/** History for a row with no bracket match — qualifying singles, doubles.
    Same response shape as getMatchScoreHistory, so the popup renders both
    through one path. */
export async function getEntryScoreHistory(entryId) {
  const { data } = await client.get(`/schedule/entries/${entryId}/score-history`)
  return data
}
