/* The leagues you're in. Reached from the dashboard. */

import { Redirect } from 'expo-router'
import { StyleSheet, Text, View } from 'react-native'
import { useAuth } from '../../auth'
import { getLeagues } from '../../api'
import { useApi } from '../../useApi'
import { C } from '../../theme'
import { Button, Card, CardLink, ErrorNote, Loading, Muted, Screen, Title } from '../../ui'

export default function Leagues() {
  const { phase, retry, error: authError } = useAuth()
  const ready = phase === 'ready'
  const { data: leagues, error, loading, refetch } = useApi(
    ready ? 'leagues' : null, getLeagues, { enabled: ready },
  )

  if (phase === 'boot') return <Loading />
  if (phase === 'signedout') return <Redirect href="/sign-in" />

  if (phase === 'unreachable') {
    return (
      <Screen>
        <Card>
          <Title>Can’t reach Upset Alert</Title>
          <Muted>
            You’re still signed in — this is a connection problem, not a
            sign-out. Your session is untouched.
          </Muted>
          {!!authError && <Muted>{authError}</Muted>}
          <Button label="Retry" onPress={retry} />
        </Card>
      </Screen>
    )
  }

  return (
    <Screen onRefresh={refetch} refreshing={loading && !!leagues}>
      {loading && !leagues ? <Loading /> : null}
      <ErrorNote error={error} onRetry={refetch} />

      {leagues?.length === 0 && (
        <Card>
          <Title>No leagues yet</Title>
          <Muted>
            Join or create a league on the website and it will appear here.
          </Muted>
        </Card>
      )}

      {leagues?.map(l => <LeagueRow key={l.id} league={l} />)}

    </Screen>
  )
}

function LeagueRow({ league }) {
  return (
    <CardLink href={`/league/${league.id}`} style={s.card}>
      <View style={s.cardTop}>
        <Text style={s.name} numberOfLines={2}>{league.name}</Text>
        <Text style={s.chev}>›</Text>
      </View>
      <Text style={s.meta}>
        {league.member_count} {league.member_count === 1 ? 'member' : 'members'}
        {league.is_public ? ' · public' : ''}
      </Text>
    </CardLink>
  )
}

const s = StyleSheet.create({
  hello: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  who: { color: C.muted, fontWeight: '700' },
  statusLink: { color: C.accent, fontWeight: '700', padding: 6 },
  card: {
    backgroundColor: C.card, borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: C.border, gap: 6,
  },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  name: { color: C.ink, fontWeight: '800', fontSize: 17, flex: 1 },
  chev: { color: C.muted, fontSize: 22, lineHeight: 22 },
  meta: { color: C.muted },
})
