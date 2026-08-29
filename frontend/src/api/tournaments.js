import client, { LONG_MS } from './client'

export const listTournaments = () => client.get('/tournaments').then(r => r.data)
export const getTournament = (id) => client.get(`/tournaments/${id}`).then(r => r.data)
export const getDraw = (id) => client.get(`/tournaments/${id}/draw`).then(r => r.data)
export const createTournament = (data) => client.post('/tournaments', data).then(r => r.data)
export const refreshDraw = (id) =>
  client.post(`/tournaments/${id}/refresh`, null, { timeout: LONG_MS }).then(r => r.data)
export const refreshAllCompleted = () =>
  client.post('/tournaments/refresh-completed', null, { timeout: LONG_MS }).then(r => r.data)
export const syncTournaments = () =>
  client.post('/tournaments/sync-tournaments', null, { timeout: LONG_MS }).then(r => r.data)
export const getTournamentCompetitors = (id) => client.get(`/tournaments/${id}/competitors`).then(r => r.data)
export const getGlobalStandings = (id) => client.get(`/tournaments/${id}/standings`).then(r => r.data)
// leagueId null = Global (every participant in the draw)
export const getMatchScoreHistory = (id, matchId) =>
  client.get(`/tournaments/${id}/matches/${matchId}/score-history`).then(r => r.data)
export const getMatchPredictors = (id, matchId, leagueId) =>
  client.get(`/tournaments/${id}/matches/${matchId}/predictors`, {
    params: leagueId != null ? { league_id: leagueId } : {},
  }).then(r => r.data)
export const getGlobalRoundScores = (id) => client.get(`/tournaments/${id}/global-round-scores`).then(r => r.data)
export const getGlobalDraws = () => client.get('/tournaments/global-draws').then(r => r.data)
export const getGlobalGSTotals = () => client.get('/tournaments/global-gs-totals').then(r => r.data)
export const toggleUnlockSelections = (id) => client.post(`/tournaments/${id}/toggle-unlock`).then(r => r.data)

export const getComparePicks = (tournamentId, leagueId) =>
  client.get(`/tournaments/${tournamentId}/compare-picks`,
    { params: leagueId != null ? { league_id: leagueId } : {} }).then(r => r.data)

export const getMyStandouts = (tournamentId) =>
  client.get(`/tournaments/${tournamentId}/my-standouts`).then(r => r.data)
