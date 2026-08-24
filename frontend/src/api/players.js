import client, { LONG_MS } from './client'

export const getH2H = (slug1, slug2) =>
  // Longer than the default: a pair not cached this week is scraped from
  // Tennis Explorer inside the request, and 20s cut that off — the panel then
  // said "Could not load H2H data" about a record it could perfectly well get.
  client.get('/h2h', { params: { p1: slug1, p2: slug2 }, timeout: LONG_MS })
    .then(r => r.data)

export const getPlayerForm = (slug, { beforeDrawId, beforeRound } = {}) =>
  client.get('/h2h/form', {
    params: { slug, before_draw_id: beforeDrawId, before_round: beforeRound },
  }).then(r => r.data)
