import client from './client'

export const getLogs = (params = {}) =>
  client.get('/admin/logs', { params }).then(r => r.data)

export const clearLogs = (olderThanDays = 30) =>
  client.delete('/admin/logs', { params: { older_than_days: olderThanDays } }).then(r => r.data)
