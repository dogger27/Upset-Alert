import client from './client'

export const listTournaments = () => client.get('/tournaments').then(r => r.data)
export const getTournament = (id) => client.get(`/tournaments/${id}`).then(r => r.data)
export const getDraw = (id) => client.get(`/tournaments/${id}/draw`).then(r => r.data)
export const createTournament = (data) => client.post('/tournaments', data).then(r => r.data)
export const refreshDraw = (id) => client.post(`/tournaments/${id}/refresh`).then(r => r.data)
export const refreshAllCompleted = () => client.post('/tournaments/refresh-completed').then(r => r.data)
