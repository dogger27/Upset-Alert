import client from './client'

export const listLeagues = () => client.get('/leagues').then(r => r.data)
export const getLeague = (id) => client.get(`/leagues/${id}`).then(r => r.data)
export const createLeague = (data) => client.post('/leagues', data).then(r => r.data)
export const updateLeague = (id, data) => client.put(`/leagues/${id}`, data).then(r => r.data)
export const joinLeague = (id, invite_code) =>
  client.post(`/leagues/${id}/join`, null, { params: invite_code ? { invite_code } : {} })
export const getLeagueTournaments = (id) => client.get(`/leagues/${id}/tournaments`).then(r => r.data)
export const getLeaderboard = (id, tournamentId) =>
  client.get(`/leagues/${id}/leaderboard`, { params: tournamentId != null ? { tournament_id: tournamentId } : {} }).then(r => r.data)
