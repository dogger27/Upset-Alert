/*
 * The diagnostics screen the scaffold used to be.
 *
 * Kept rather than deleted: it is the one place that answers "can this phone
 * reach the backend, is the session real, and is the Live Activity path
 * switched on" without needing a laptop. That is exactly the question worth
 * asking first when something looks wrong on a phone, and it will matter more
 * once Live Activities are actually sending.
 */

import { useAuth } from '../auth'
import { getOffer } from '../api'
import { useApi } from '../useApi'
import { Card, ErrorNote, Muted, Row, Screen, Title } from '../ui'

export default function Status() {
  const { config, me, phase } = useAuth()
  const ready = phase === 'ready'
  const offer = useApi(ready ? 'offer' : null, getOffer, { enabled: ready })

  return (
    <Screen>
      <Card>
        <Title>Connection</Title>
        <Row label="API reachable" value={config ? 'yes' : 'no'} />
        {/* "off" has two very different causes and they must not read the
            same. No bundle_id means the server has no APNs key configured at
            all; a bundle_id with live_activities false means the key is there
            and the feature is deliberately held off until a dry run has been
            watched through a tournament day. Reporting the second as "no key"
            sends anyone debugging it to look in the wrong place. */}
        <Row
          label="Live Activities"
          value={
            !config ? '—'
              : config.live_activities ? 'on'
              : config.bundle_id ? 'off (key ready, not enabled)'
              : 'off (no key configured)'
          }
        />
        {config?.bundle_id ? <Row label="Bundle" value={config.bundle_id} /> : null}
        <Row label="Signed in as" value={me?.username || '—'} />
      </Card>

      <Card>
        <Title>Worth a Lock Screen?</Title>
        <ErrorNote error={offer.error} onRetry={offer.refetch} />
        {offer.data?.match ? (
          <>
            <Row label="Match" value={String(offer.data.match.match_id)} />
            <Row label="Event" value={offer.data.match.event || '—'} />
            <Row label="Why" value={offer.data.reason} />
            <Row label="Score" value={String(offer.data.score)} />
          </>
        ) : (
          <Muted>
            Nothing live worth offering right now. During play this names one
            match and says why it was chosen.
          </Muted>
        )}
      </Card>
    </Screen>
  )
}
