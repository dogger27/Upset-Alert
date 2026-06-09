import client from './client'

export const discoverTournaments = (year) =>
  client.get(`/discover/${year}`).then(r => r.data)

export const addDiscoveredTournament = (data) =>
  client.post('/discover/add', data).then(r => r.data)
