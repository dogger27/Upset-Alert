/* The site's Forgot password page. The reset itself completes on the link the
   email carries (upsetalert.ca/reset-password), which opens in the browser —
   this screen sends it and says exactly what the site says. */
import { useState } from 'react'
import { Stack, useRouter } from 'expo-router'
import { StyleSheet, Text, TextInput } from 'react-native'
import { forgotPassword } from '../api'
import { C, TOUCH } from '../theme'
import { Button, Card, Muted, Screen, Title } from '../ui'

export default function ForgotPassword() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!email) return
    setBusy(true); setError('')
    try { await forgotPassword(email.trim()); setSent(true) }
    catch (e) { setError(e.offline ? 'Could not reach Upset Alert.' : (e.message || 'Could not send')) }
    finally { setBusy(false) }
  }

  return (
    <>
      <Stack.Screen options={{ title: 'Forgot password' }} />
      <Screen>
        <Card>
          <Title>Forgot password</Title>
          {sent ? (
            <Muted>If that email is registered, you’ll receive a reset link shortly.</Muted>
          ) : (
            <>
              <TextInput style={s.input} value={email} onChangeText={setEmail} placeholder="you@example.com"
                         placeholderTextColor={C.muted} autoCapitalize="none" autoCorrect={false}
                         keyboardType="email-address" autoComplete="email" textContentType="emailAddress"
                         returnKeyType="send" onSubmitEditing={submit} autoFocus />
              {!!error && <Text style={{ color: C.bad }}>{error}</Text>}
              <Button label="Send reset link" onPress={submit} busy={busy} />
            </>
          )}
          <Button label="Back to log in" quiet onPress={() => router.back()} />
        </Card>
      </Screen>
    </>
  )
}

const s = StyleSheet.create({
  input: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12, height: TOUCH, fontSize: 16, color: C.ink },
})
