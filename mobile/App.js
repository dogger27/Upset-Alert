/*
 * First screen: prove the whole chain from a phone.
 *
 * Deliberately not a pretty shell over nothing. Signing in against production
 * and reading back a real answer is what tells us the parts that CANNOT be
 * checked from a laptop actually work: the phone reaches the Cloudflare Tunnel,
 * the JWT is accepted from a non-browser client, and the /app surface built for
 * this app answers it.
 *
 * Runs in Expo Go, so it uses no native modules — no SecureStore, no push. The
 * token is held in memory and a restart signs you out again, which is correct
 * for a scaffold and wrong for the real app: that one puts it in the Keychain,
 * because WebKit-style storage eviction signing people out silently is a
 * failure this project has already had once on the web.
 */

import { useEffect, useState } from 'react'
import {
  ActivityIndicator, SafeAreaView, ScrollView, StyleSheet, Text,
  TextInput, TouchableOpacity, View,
} from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { getAppConfig, getMe, getOffer, login, setToken } from './api'

export default function App() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [me, setMe] = useState(null)
  const [config, setConfig] = useState(null)
  const [offer, setOffer] = useState(null)

  // Public, so it answers before anyone signs in — and it is the fastest way to
  // tell "the phone cannot reach the API" from "the password is wrong".
  useEffect(() => {
    getAppConfig().then(setConfig).catch(e => setError(`Cannot reach the API: ${e.message}`))
  }, [])

  async function signIn() {
    setBusy(true); setError('')
    try {
      const { access_token } = await login(email.trim(), password)
      setToken(access_token)
      setMe(await getMe())
      // Nothing is live at 3am, so an empty answer here is a real answer.
      setOffer(await getOffer().catch(() => null))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <SafeAreaView style={s.safe}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={s.body}>
        <Text style={s.brand}>UPSET <Text style={s.brandAccent}>ALERT!</Text></Text>

        <Row label="API reachable" value={config ? 'yes' : '…'} />
        {config && (
          <Row label="Live Activities" value={config.live_activities ? 'on' : 'off (no key yet)'} />
        )}

        {!me ? (
          <View style={s.card}>
            <Text style={s.cardTitle}>Sign in</Text>
            <TextInput
              style={s.input} placeholder="Email" placeholderTextColor="#6b7a75"
              autoCapitalize="none" autoCorrect={false} keyboardType="email-address"
              value={email} onChangeText={setEmail}
            />
            <TextInput
              style={s.input} placeholder="Password" placeholderTextColor="#6b7a75"
              secureTextEntry value={password} onChangeText={setPassword}
            />
            <TouchableOpacity style={s.button} onPress={signIn} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" />
                    : <Text style={s.buttonText}>Sign in</Text>}
            </TouchableOpacity>
          </View>
        ) : (
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
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  rowLabel: { color: '#93a49e' },
  rowValue: { color: '#eef2f0', fontWeight: '600', flexShrink: 1, textAlign: 'right' },
  muted: { color: '#93a49e' },
  error: { color: '#f87171' },
})
