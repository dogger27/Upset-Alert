import client from './client'

export const listLeagues = () => client.get('/leagues').then(r => r.data)
export const getLeague = (id) => client.get(`/leagues/${id}`).then(r => r.data)
export const createLeague = (data) => client.post('/leagues', data).then(r => r.data)
export const updateLeague = (id, data) => client.put(`/leagues/${id}`, data).then(r => r.data)
export const joinLeague = (invite_code) =>
  client.post('/leagues/join', null, { params: { invite_code } })
export const deleteLeague = (id) => client.delete(`/leagues/${id}`)
export const setMemberAdmin = (leagueId, userId, isAdmin) =>
  client.put(`/leagues/${leagueId}/members/${userId}/admin`, null, { params: { is_admin: isAdmin } })
export const removeMember = (leagueId, userId) =>
  client.delete(`/leagues/${leagueId}/members/${userId}`)
export const getLeagueTournaments = (id) => client.get(`/leagues/${id}/tournaments`).then(r => r.data)
export const getLeaderboard = (id, tournamentId) =>
  client.get(`/leagues/${id}/leaderboard`, { params: tournamentId != null ? { tournament_id: tournamentId } : {} }).then(r => r.data)
export const getRoundScores = (leagueId, tournamentId) =>
  client.get(`/leagues/${leagueId}/round-scores`, { params: { tournament_id: tournamentId } }).then(r => r.data)
