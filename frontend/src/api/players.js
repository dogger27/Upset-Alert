import client from './client'

export const getH2H = (slug1, slug2) =>
  client.get('/h2h', { params: { p1: slug1, p2: slug2 } }).then(r => r.data)
