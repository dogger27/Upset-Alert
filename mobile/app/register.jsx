/*
 * Create an account — the site's Register page, then its code step.
 *
 * Two screens in one: the form, then "Check your email" with the six-digit
 * code. Login refuses an unverified address, so the code is not optional; on
 * success the app signs in with the same credentials rather than bouncing the
 * reader back to a form they just filled in. Payload matches the site's store:
 * display_name is the full name.
 */
import { useState } from 'react'
import { Link, Redirect, Stack } from 'expo-router'
import { StyleSheet, Text, TextInput, View } from 'react-native'
import { register, verifyEmailCode } from '../api'
import { useAuth } from '../auth'
import { C, TOUCH } from '../theme'
import { Button, Card, Muted, Screen, Title } from '../ui'

export default function Register() {
  const { signIn, phase } = useAuth()
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState('form')     // form | code
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (phase === 'ready') return <Redirect href="/" />

  async function submit() {
    setError('')
    if (password !== confirm) { setError('Passwords do not match'); return }
    if (password.length < 8) { setError('Password must be at least 8 characters'); return }
    setBusy(true)
    try {
      await register({ email: email.trim(), username: username.trim(), full_name: fullName.trim(),
                       display_name: fullName.trim(), password })
      setStep('code')
    } catch (e) {
      setError(e.offline ? 'Could not reach Upset Alert.' : (e.message || 'Could not create account'))
    } finally { setBusy(false) }
  }

  async function verify() {
    setError(''); setBusy(true)
    try {
      await verifyEmailCode(email.trim(), code.trim())
      await signIn(email.trim(), password)
    } catch (e) {
      setError(e.offline ? 'Could not reach Upset Alert.' : (e.message || 'Invalid or expired code'))
    } finally { setBusy(false) }
  }

  return (
    <>
      <Stack.Screen options={{ title: 'Create account' }} />
      <Screen>
        <Card>
          {step === 'code' ? (
            <>
              <Title>Check your email</Title>
              <Muted>We sent a verification code to {email.trim()}.</Muted>
              <Text style={s.label}>Verification code</Text>
              <TextInput style={[s.input, s.code]} value={code} onChangeText={setCode} placeholder="000000"
                         placeholderTextColor={C.muted} keyboardType="number-pad" textContentType="oneTimeCode"
                         autoComplete="one-time-code" maxLength={6} autoFocus returnKeyType="go" onSubmitEditing={verify} />
              {!!error && <Text style={s.error}>{error}</Text>}
              <Button label="Verify and sign in" onPress={verify} busy={busy} />
            </>
          ) : (
            <>
              <Title>Create account</Title>
              <Text style={s.label}>Username</Text>
              <TextInput style={s.input} value={username} onChangeText={setUsername} placeholder="Your unique handle"
                         placeholderTextColor={C.muted} autoCapitalize="none" autoCorrect={false} autoComplete="username-new" textContentType="username" />
              <Text style={s.label}>Full name</Text>
              <TextInput style={s.input} value={fullName} onChangeText={setFullName} placeholder="Your full name"
                         placeholderTextColor={C.muted} autoComplete="name" textContentType="name" />
              <Text style={s.label}>Email</Text>
              <TextInput style={s.input} value={email} onChangeText={setEmail} placeholder="you@example.com"
                         placeholderTextColor={C.muted} autoCapitalize="none" autoCorrect={false}
                         keyboardType="email-address" autoComplete="email" textContentType="emailAddress" />
              <Text style={s.label}>Password</Text>
              <TextInput style={s.input} value={password} onChangeText={setPassword} placeholder="At least 8 characters"
                         placeholderTextColor={C.muted} secureTextEntry autoCapitalize="none" autoCorrect={false}
                         autoComplete="new-password" textContentType="newPassword" />
              <Text style={s.label}>Confirm password</Text>
              <TextInput style={s.input} value={confirm} onChangeText={setConfirm} placeholder="Confirm password"
                         placeholderTextColor={C.muted} secureTextEntry autoCapitalize="none" autoCorrect={false}
                         autoComplete="new-password" textContentType="newPassword" returnKeyType="go" onSubmitEditing={submit} />
              {!!error && <Text style={s.error}>{error}</Text>}
              <Button label="Create account" onPress={submit} busy={busy} />
            </>
          )}
          <View style={{ alignItems: 'center', paddingTop: 4 }}>
            <Link href="/sign-in" style={s.link}>Already have an account? Sign in</Link>
          </View>
        </Card>
      </Screen>
    </>
  )
}

const s = StyleSheet.create({
  label: { color: C.muted, fontFamily: 'SairaCondensed_700Bold', fontSize: 12, letterSpacing: 1.1, textTransform: 'uppercase' },
  input: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12, height: TOUCH, fontSize: 16, color: C.ink },
  code: { fontFamily: 'SairaCondensed_600SemiBold', fontSize: 24, letterSpacing: 6, textAlign: 'center' },
  error: { color: C.bad },
  link: { color: C.greenLit, fontFamily: 'Archivo_500Medium', fontSize: 14, paddingVertical: 4 },
})
