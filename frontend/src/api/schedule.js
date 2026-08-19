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
