import client from './client'

export const getPredictions = (tournamentId) =>
  client.get(`/predictions/${tournamentId}`).then(r => r.data)

export const savePredictions = (tournamentId, picks) =>
  client.put(`/predictions/${tournamentId}`, { picks }).then(r => r.data)
