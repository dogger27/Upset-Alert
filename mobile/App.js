/*
 * First screen: prove the whole chain from a phone, and stay signed in.
 *
 * The launch path is the interesting part. When a stored token exists we have
 * to find out whether it is still good, and there are exactly two ways that
 * can fail — which must NOT be shown the same way:
 *
 *   401            the session is genuinely dead   -> clear it, show sign-in
 *   never arrived  the network is                  -> KEEP it, offer Retry
 *
 * Showing a sign-in form for the second case is the bug worth naming: it
 * invites someone to re-authenticate over a problem that fixes itself, and it
 * is indistinguishable to them from having been logged out. Tokens here are
 * year-long and rolling, so "looks broken" is nearly always transport.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  ActivityIndicator, ScrollView, StyleSheet, Text,
  TextInput, TouchableOpacity, View,
} from 'react-native'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import { StatusBar } from 'expo-status-bar'
import { getAppConfig, getMe, getOffer, login, setToken } from './api'
import { clearToken, loadToken, saveToken } from './session'

export default function App() {
  return (
    <SafeAreaProvider>
      <Root />
    </SafeAreaProvider>
  )
}

function Root() {
  const [phase, setPhase] = useState('boot')   // boot | signedout | unreachable | ready
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [me, setMe] = useState(null)
  const [config, setConfig] = useState(null)
  const [offer, setOffer] = useState(null)

  // Public, so it answers before anyone signs in — and it is the fastest way
  // to tell "the phone cannot reach the API" from "the password is wrong".
  useEffect(() => { getAppConfig().then(setConfig).catch(() => setConfig(null)) }, [])

  const loadSignedIn = useCallback(async () => {
    setMe(await getMe())
    // Nothing is live at 3am, so an empty answer here is a real answer.
    setOffer(await getOffer().catch(() => null))
    setPhase('ready')
  }, [])

  const boot = useCallback(async () => {
    setError('')
    const stored = await loadToken()
    if (!stored) { setPhase('signedout'); return }
    setToken(stored)
    try {
      await loadSignedIn()
    } catch (e) {
      if (e.status === 401) {
        // The ONLY branch allowed to end a session.
        await clearToken()
        setToken(null)
        setPhase('signedout')
      } else {
        setError(e.message)
        setPhase('unreachable')
      }
    }
  }, [loadSignedIn])

  useEffect(() => { boot() }, [boot])

  async function signIn() {
    setBusy(true); setError('')
    try {
      const { access_token } = await login(email.trim(), password)
      setToken(access_token)
      await saveToken(access_token)
      setPassword('')
      await loadSignedIn()
    } catch (e) {
      setError(e.offline ? `Cannot reach Upset Alert: ${e.message}` : e.message)
    } finally {
      setBusy(false)
    }
  }

  async function signOut() {
    await clearToken()
    setToken(null)
    setMe(null); setOffer(null)
    setPhase('signedout')
  }

  if (phase === 'boot') {
    return (
      <SafeAreaView style={[s.safe, s.centre]}>
        <StatusBar style="light" />
        <ActivityIndicator color="#c9783a" size="large" />
      </SafeAreaView>
    )
  }

  return (
    <SafeAreaView style={s.safe}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={s.body}>
        <Text style={s.brand}>UPSET <Text style={s.brandAccent}>ALERT!</Text></Text>

        <Row label="API reachable" value={config ? 'yes' : 'no'} />
        {config && (
          <Row label="Live Activities" value={config.live_activities ? 'on' : 'off (no key yet)'} />
        )}

        {phase === 'unreachable' && (
          <View style={s.card}>
            <Text style={s.cardTitle}>Can’t reach Upset Alert</Text>
            <Text style={s.muted}>
              You’re still signed in — this is a connection problem, not a
              sign-out. Your session is untouched.
            </Text>
            <TouchableOpacity style={s.button} onPress={boot}>
              <Text style={s.buttonText}>Retry</Text>
            </TouchableOpacity>
          </View>
        )}

        {phase === 'signedout' && (
          <View style={s.card}>
            <Text style={s.cardTitle}>Sign in</Text>
            <TextInput
              style={s.input} placeholder="Email" placeholderTextColor="#6b7a75"
              autoCapitalize="none" autoCorrect={false} keyboardType="email-address"
              textContentType="username" value={email} onChangeText={setEmail}
            />
            <TextInput
              style={s.input} placeholder="Password" placeholderTextColor="#6b7a75"
              secureTextEntry textContentType="password"
              value={password} onChangeText={setPassword}
            />
            <TouchableOpacity style={s.button} onPress={signIn} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" />
                    : <Text style={s.buttonText}>Sign in</Text>}
            </TouchableOpacity>
          </View>
        )}

        {phase === 'ready' && me && (
          <View style={s.card}>
            <Text style={s.cardTitle}>Signed in</Text>
            <Row label="User" value={me.username} />
            <Row label="Name" value={me.full_name} />

            <Text style={[s.cardTitle, { marginTop: 18 }]}>Worth a Lock Screen?</Text>
            {offer && offer.match ? (
              <>
                <Row label="Match" value={String(offer.match.match_id)} />
                <Row label="Event" value={offer.match.event || '—'} />
                <Row label="Why" value={offer.reason} />
                <Row label="Score" value={String(offer.score)} />
              </>
            ) : (
              <Text style={s.muted}>Nothing live worth offering right now.</Text>
            )}

            <TouchableOpacity style={s.buttonQuiet} onPress={signOut}>
              <Text style={s.buttonQuietText}>Sign out</Text>
            </TouchableOpacity>
          </View>
        )}

        {!!error && <Text style={s.error}>{error}</Text>}
      </ScrollView>
    </SafeAreaView>
  )
}

function Row({ label, value }) {
  return (
    <View style={s.row}>
      <Text style={s.rowLabel}>{label}</Text>
      <Text style={s.rowValue}>{value}</Text>
    </View>
  )
}

/* The web app's dark palette, roughly. Not a design — a scaffold that does not
   look like a default template, so a screenshot of it is legible. */
const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#101a16' },
  centre: { alignItems: 'center', justifyContent: 'center' },
  body: { padding: 20, gap: 14 },
  brand: { fontSize: 26, fontWeight: '800', color: '#eef2f0', letterSpacing: 0.5 },
  brandAccent: { color: '#c9783a' },
  card: {
    backgroundColor: '#182521', borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: '#3a4b45', gap: 10,
  },
  cardTitle: { color: '#eef2f0', fontWeight: '800', fontSize: 16 },
  input: {
    backgroundColor: '#101a16', borderWidth: 1, borderColor: '#3a4b45',
    borderRadius: 10, paddingHorizontal: 12,
    // 44 to match the touch-target rule the web app now follows, and 16px text
    // because anything smaller makes iOS zoom the field on focus.
    height: 44, fontSize: 16, color: '#eef2f0',
  },
  button: {
    backgroundColor: '#2d6a4f', borderRadius: 10, height: 44,
    alignItems: 'center', justifyContent: 'center',
  },
  buttonText: { color: '#fff', fontWeight: '800' },
  buttonQuiet: {
    marginTop: 18, height: 44, borderRadius: 10, borderWidth: 1,
    borderColor: '#3a4b45', alignItems: 'center', justifyContent: 'center',
  },
  buttonQuietText: { color: '#93a49e', fontWeight: '700' },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  rowLabel: { color: '#93a49e' },
  rowValue: { color: '#eef2f0', fontWeight: '600', flexShrink: 1, textAlign: 'right' },
  muted: { color: '#93a49e' },
  error: { color: '#f87171' },
})
