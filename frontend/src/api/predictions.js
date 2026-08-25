import client from './client'

export const getPredictions = (tournamentId, userId) =>
  client.get(`/predictions/${tournamentId}`, { params: userId != null ? { user_id: userId } : {} }).then(r => r.data)

/* One automatic retry on a TIMED-OUT save. The request can die between the
   browser and the edge with the server perfectly healthy (2026-08-25:
   desktop saves timed out at exactly the client's 20s while probes ran 200s
   in the same seconds, on a line with a QUIC history). The payload is the
   FULL pick set, so replaying it is safe whether or not the first attempt
   landed — the second write is identical. Only timeouts retry: a 4xx/5xx is
   an answer, and answers are handled where they always were. */
const withTimeoutRetry = (fn) => async (...args) => {
  try {
    return await fn(...args)
  } catch (err) {
    if (err?.code !== 'ECONNABORTED') throw err
    return fn(...args)
  }
}

export const savePredictions = withTimeoutRetry((tournamentId, picks, userId) =>
  client.put(`/predictions/${tournamentId}`, { picks }, { params: userId != null ? { user_id: userId } : {} }).then(r => r.data))

export const getEntryStatus = () =>
  client.get('/predictions/entry-status').then(r => r.data)
