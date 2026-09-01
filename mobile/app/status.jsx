/*
 * The diagnostics screen the scaffold used to be.
 *
 * Kept rather than deleted: it is the one place that answers "can this phone
 * reach the backend, is the session real, and is the Live Activity path
 * switched on" without needing a laptop. That is exactly the question worth
 * asking first when something looks wrong on a phone, and it will matter more
 * once Live Activities are actually sending.
 */

import Constants from 'expo-constants'
import { useAuth } from '../auth'
import { getOffer } from '../api'
import { useApi } from '../useApi'
import { capabilities, isAvailable } from '../modules/live-activity'
import { Card, ErrorNote, Muted, Row, Screen, Title } from '../ui'

export default function Status() {
  const { config, me, phase } = useAuth()
  const ready = phase === 'ready'
  const offer = useApi(ready ? 'offer' : null, getOffer, { enabled: ready })

  // Which BINARY is running, and what native code is in it. Added after an
  // afternoon of guessing whether a given build was actually installed: the JS
  // reloads from Metro constantly, so the version on screen tells you nothing
  // about the binary underneath it. nativeBuildVersion does.
  const caps = capabilities()

  return (
    <Screen>
      <Card>
        <Title>This build</Title>
        <Row label="App version" value={Constants.nativeAppVersion || '—'} />
        <Row label="Build number" value={Constants.nativeBuildVersion || '—'} />
        <Row label="Live Activity module" value={isAvailable() ? 'present' : 'ABSENT'} />
        <Row label="ActivityKit" value={caps.supported ? 'supported' : 'no'} />
        <Row label="Activities allowed" value={caps.enabled ? 'yes' : 'no (check Settings)'} />
        <Row label="Push-to-start" value={caps.pushToStart ? 'yes' : 'no (needs iOS 17.2)'} />
      </Card>

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
