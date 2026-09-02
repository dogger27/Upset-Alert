/* The site's About page: the note from Paul, the contact form, and what runs
   under the hood — copy verbatim. */
import { useState } from 'react'
import { Stack } from 'expo-router'
import { StyleSheet, Text, TextInput } from 'react-native'
import { sendContact } from '../api'
import { C, S, T } from '../theme'
import { Button, Card, Muted, Screen, Title } from '../ui'

export default function About() {
  const [form, setForm] = useState({ name: '', email: '', subject: '', body: '' })
  const [status, setStatus] = useState('idle')   // idle | sending | sent | error
  const set = k => v => setForm(f => ({ ...f, [k]: v }))
  const canSend = form.name && form.email && form.subject && form.body

  async function send() {
    setStatus('sending')
    try { await sendContact(form); setStatus('sent') }
    catch { setStatus('error') }
  }

  return (
    <>
      <Stack.Screen options={{ title: 'About' }} />
      <Screen>
        <Card>
          <Title>Paul Wiens</Title>
          <Muted>Tennis enthusiast · Stats nerd · Developer at ILM / Disney</Muted>
          <Muted>
            Upset Alert! is a hobby project born out of a love for tennis and the fun of
            picking tournament draws with friends. It’s completely free to play — create a
            league, invite your crew, and see who can predict the most upsets.
          </Muted>
          <Muted>I built this for the community to enjoy. No subscriptions, no ads, no catches.</Muted>
        </Card>

        <Card>
          <Title>Contact</Title>
          <Muted>Please connect with me for bug fixes, feature requests, or a friendly hello!</Muted>
          {status === 'sent' ? (
            <Text style={{ color: C.greenLit }}>Message sent! I’ll get back to you soon.</Text>
          ) : (
            <>
              <Text style={s.label}>Name</Text>
              <TextInput style={s.input} value={form.name} onChangeText={set('name')} placeholderTextColor={C.muted} autoComplete="name" />
              <Text style={s.label}>Your email</Text>
              <TextInput style={s.input} value={form.email} onChangeText={set('email')} placeholderTextColor={C.muted}
                         keyboardType="email-address" autoCapitalize="none" autoComplete="email" />
              <Text style={s.label}>Subject</Text>
              <TextInput style={s.input} value={form.subject} onChangeText={set('subject')} placeholderTextColor={C.muted} />
              <Text style={s.label}>Message</Text>
              <TextInput style={[s.input, s.area]} value={form.body} onChangeText={set('body')} placeholderTextColor={C.muted}
                         multiline numberOfLines={5} textAlignVertical="top" />
              {status === 'error' && <Text style={{ color: C.bad }}>Something went wrong — please try again.</Text>}
              <Button label={status === 'sending' ? 'Sending…' : 'Send message'} onPress={send} busy={status === 'sending'} />
              {!canSend && <Muted>All four fields are needed.</Muted>}
            </>
          )}
        </Card>

        <Card>
          <Title>Under the hood</Title>
          <Text style={s.sub}>🌐 Data sources</Text>
          {[
            'Wikipedia: Tournament Data & Draws',
            'Sofascore: Live Point-by-Point Scores & Match Results',
            'ESPN: Live Score & Results Cross-Check',
            'ATP/WTA Official Order of Play: Daily Schedules',
            'Tennis Explorer: Weekly Rankings, Elo & Player Data',
          ].map(l => <Text key={l} style={s.li}>• {l}</Text>)}
          <Text style={s.sub}>Fully autonomous</Text>
          <Muted>
            The site runs itself. Draw results, tournament schedules, player seedings, and
            rankings all stay current automatically — and every published schedule is
            verified against the official sheet by an autonomous AI agent that repairs
            what it finds. No admin intervention required.
          </Muted>
        </Card>
      </Screen>
    </>
  )
}

const s = StyleSheet.create({
  label: { ...T.eyebrow, color: C.muted, marginTop: S.xs },
  input: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 12, height: 44, fontSize: 16, color: C.ink },
  area: { height: 120, paddingTop: 10 },
  sub: { ...T.smallMed, color: C.ink, marginTop: S.xs },
  li: { ...T.small, color: C.inkBody, paddingLeft: 4 },
})
