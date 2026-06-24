import client from './client'

export const getLogs = (params = {}) =>
  client.get('/admin/logs', { params }).then(r => r.data)

export const clearLogs = (olderThanDays = 30) =>
  client.delete('/admin/logs', { params: { older_than_days: olderThanDays } }).then(r => r.data)

export const getAdminPlayers = (params = {}) =>
  client.get('/admin/players', { params }).then(r => r.data)

export const getRankingsWeeks = () =>
  client.get('/admin/rankings/weeks').then(r => r.data)

export const getAdminRankings = (params = {}) =>
  client.get('/admin/rankings', { params }).then(r => r.data)
