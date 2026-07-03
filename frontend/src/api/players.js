import client from './client'

export const getH2H = (slug1, slug2) =>
  client.get('/h2h', { params: { p1: slug1, p2: slug2 } }).then(r => r.data)

export const getPlayerForm = (slug, { beforeDrawId, beforeRound } = {}) =>
  client.get('/h2h/form', {
    params: { slug, before_draw_id: beforeDrawId, before_round: beforeRound },
  }).then(r => r.data)
