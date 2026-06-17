import client from './client'

export const getPredictions = (tournamentId, userId) =>
  client.get(`/predictions/${tournamentId}`, { params: userId != null ? { user_id: userId } : {} }).then(r => r.data)

export const savePredictions = (tournamentId, picks) =>
  client.put(`/predictions/${tournamentId}`, { picks }).then(r => r.data)

export const getEntryStatus = () =>
  client.get('/predictions/entry-status').then(r => r.data)
