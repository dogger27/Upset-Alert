import { useState } from 'react'
import { Redirect } from 'expo-router'
import { StyleSheet, Text, TextInput, View } from 'react-native'
import { useAuth } from '../auth'
import { C, TOUCH } from '../theme'
import { Button, Card, Muted, Screen, Title } from '../ui'

export default function SignIn() {
  const { signIn, config, phase } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Signing in changes `phase` but does not move the app: this screen would
  // otherwise keep rendering the form over an authenticated session, which is
  // exactly what it did — the sign-in worked, the token was stored, and only
  // relaunching (which boots at "/") revealed it. Declarative rather than a
  // router.replace() inside submit(), so arriving here while already signed in
  // bounces too, not just the instant the request returns.
  //
  // Placed AFTER every hook above: early-returning before one is the
  // rules-of-hooks bug this project has hit before.
  if (phase === 'ready') return <Redirect href="/" />

  async function submit() {
    setBusy(true); setError('')
    try {
      await signIn(email, password)
      setPassword('')
    } catch (e) {
      // Distinguishing these two is the whole reason api.js carries .offline.
      setError(e.offline ? 'Could not reach Upset Alert. Check your connection.' : e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Screen>
      <View style={s.head}>
        <Text style={s.brand}>UPSET <Text style={s.accent}>ALERT!</Text></Text>
        <Muted>Sign in to see your leagues and standings.</Muted>
      </View>

      <Card>
        <Title>Sign in</Title>
        <TextInput
          style={s.input} placeholder="Email" placeholderTextColor={C.muted}
          autoCapitalize="none" autoCorrect={false} keyboardType="email-address"
          autoComplete="username" textContentType="username"
          value={email} onChangeText={setEmail}
          onSubmitEditing={submit} returnKeyType="next"
        />
        {/* autoCapitalize and autoCorrect are NOT redundant with
            secureTextEntry: iOS hides the correction bar for a secure field,
            but the shift key can still be armed, so a password typed into a
            fresh field can arrive with a capitalised first letter and no
            visible sign — the characters render as dots either way. */}
        <TextInput
          style={s.input} placeholder="Password" placeholderTextColor={C.muted}
          secureTextEntry autoCapitalize="none" autoCorrect={false}
          autoComplete="current-password" textContentType="password"
          value={password} onChangeText={setPassword}
          onSubmitEditing={submit} returnKeyType="go"
        />
        <Button label="Sign in" onPress={submit} busy={busy} />
        {!!error && <Text style={s.error}>{error}</Text>}
      </Card>

      {config === null && (
        <Muted>Can’t reach the server right now — signing in will fail until it comes back.</Muted>
      )}
    </Screen>
  )
}

const s = StyleSheet.create({
  head: { gap: 6, paddingTop: 24, paddingBottom: 8 },
  brand: { fontSize: 30, fontWeight: '800', color: C.ink, letterSpacing: 0.5 },
  accent: { color: C.accent },
  input: {
    backgroundColor: C.bg, borderWidth: 1, borderColor: C.border,
    borderRadius: 10, paddingHorizontal: 12,
    // 16px or iOS zooms the field on focus; TOUCH to match the web app's rule.
    height: TOUCH, fontSize: 16, color: C.ink,
  },
  error: { color: C.error },
})
