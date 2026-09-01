/*
 * The diagnostics screen the scaffold used to be.
 *
 * Kept rather than deleted: it is the one place that answers "can this phone
 * reach the backend, is the session real, and is the Live Activity path
 * switched on" without needing a laptop. That is exactly the question worth
 * asking first when something looks wrong on a phone, and it will matter more
 * once Live Activities are actually sending.
 */

import { useState } from 'react'
import { Text } from 'react-native'
import Constants from 'expo-constants'
import { useAuth } from '../auth'
import { getOffer } from '../api'
import { useApi } from '../useApi'
import { capabilities, isAvailable } from '../modules/live-activity'
import { showOnLockScreen, useShowingOnLockScreen } from '../liveactivity'
import { C } from '../theme'
import { Button, Card, ErrorNote, Muted, Row, Screen, Title } from '../ui'

export default function Status() {
  const { config, me, phase } = useAuth()
  const ready = phase === 'ready'
  const offer = useApi(ready ? 'offer' : null, getOffer, { enabled: ready })

  // Which BINARY is running, and what native code is in it. Added after an
  // afternoon of guessing whether a given build was actually installed: the JS
  // reloads from Metro constantly, so the version on screen tells you nothing
  // about the binary underneath it. nativeBuildVersion does.
  const caps = capabilities()
  const [starting, setStarting] = useState(false)
  const [startErr, setStartErr] = useState('')
  const [started, recheck] = useShowingOnLockScreen(offer.data?.match?.match_id)

  async function show() {
    setStarting(true); setStartErr('')
    try {
      await showOnLockScreen(offer.data?.match, config?.content_state_version ?? 1)
    } catch (e) {
      setStartErr(e.message)
    } finally {
      setStarting(false); recheck()
    }
  }

  return (
    <Screen>
      <Card>
        <Title>This build</Title>
        {/* nativeAppVersion/nativeBuildVersion were removed from
            expo-constants; they live in expo-application now, which is another
            native module and therefore another build — circular, when the thing
            being diagnosed IS which build is installed.
            The module row is the honest answer instead: it is present only in a
            binary built after the podspec landed, so it identifies the build
            more reliably than a version string would. */}
        <Row label="App version" value={Constants.expoConfig?.version || '—'} />
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
            {offer.data.match.attributes && (
              <Row
                label="Match"
                value={`${offer.data.match.attributes.p1_name} v ${offer.data.match.attributes.p2_name}`}
              />
            )}
            <Row label="Event" value={offer.data.match.event || '—'} />
            <Row label="Round" value={offer.data.match.attributes?.round_name || '—'} />
            <Row label="Why" value={offer.data.reason} />
            <Row label="Score" value={String(offer.data.score)} />

            {started ? (
              <Muted>On your Lock Screen now. It updates as the match moves.</Muted>
            ) : (
              <Button
                label={isAvailable() ? 'Show on Lock Screen' : 'Not available in this build'}
                onPress={show}
                busy={starting}
              />
            )}
            {!!startErr && <Text style={{ color: C.error }}>{startErr}</Text>}
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
