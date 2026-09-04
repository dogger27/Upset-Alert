/* The site's About page: the photo and note from Paul, how to add the web app
   to a home screen, the contact form, and what runs under the hood — copy
   verbatim, so the three places a reader can meet this page (desktop, mobile
   browser / PWA, this app) say exactly the same thing. */
import { useState } from 'react'
import { Stack } from 'expo-router'
import { Image, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { sendContact } from '../api'
import { C, S, T } from '../theme'
import { leading } from '../fontScale.js'
import { Button, Card, Muted, Screen, Title } from '../ui'

/* The photo and the install screenshots ship WITH the app (assets/about/,
   copied from frontend/public). Fetching them from the site would have made
   this page depend on the network and on the site being deployed first — the
   photo rendered as an empty box until then. ~155 KB for four files, behind a
   tap for three of them. Update these alongside the site's copies. */
const PHOTO = require('../assets/about/paul-wiens.jpg')
const SHOTS = {
  'safari-more': require('../assets/about/safari-more.jpg'),
  'safari-share': require('../assets/about/safari-share.jpg'),
  'add-to-home': require('../assets/about/add-to-home.jpg'),
}

/* One platform's instructions, closed until tapped — the site's <details>,
   which React Native has no equivalent of. */
function Steps({ os, meta, children, open, onToggle }) {
  return (
    <View style={s.acc}>
      <Pressable onPress={onToggle} style={({ pressed }) => [s.accHead, pressed && { opacity: 0.7 }]}
                 accessibilityRole="button" accessibilityState={{ expanded: open }}
                 accessibilityLabel={`${os} instructions`}>
        <Text style={s.accOs}>{os}</Text>
        <Text style={s.accMeta}>{meta}</Text>
        <Text style={s.accChev}>{open ? '\u2303' : '\u2304'}</Text>
      </Pressable>
      {open ? <View style={s.accBody}>{children}</View> : null}
    </View>
  )
}

const Step = ({ n, children }) => (
  <View style={s.step}>
    <Text style={s.stepNum}>{n}.</Text>
    <Text style={s.stepText}>{children}</Text>
  </View>
)

/* MEASURED, NOT `aspectRatio`. A ratio on the Image left a box taller than the
   picture, letterboxed in grey — the row's width is what is known here, so the
   height is computed from it and the picture fills the box exactly. */
function Shot({ src, w, h, alt }) {
  const [width, setWidth] = useState(0)
  return (
    <View style={s.shotWrap} onLayout={e => setWidth(e.nativeEvent.layout.width)}>
      {width > 0 ? (
        <Image source={SHOTS[src]} accessibilityLabel={alt} resizeMode="contain"
               style={[s.shot, { width, height: Math.round((width * h) / w) }]} />
      ) : null}
    </View>
  )
}

export default function About() {
  const [form, setForm] = useState({ name: '', email: '', subject: '', body: '' })
  const [status, setStatus] = useState('idle')   // idle | sending | sent | error
  // One open at a time, both closed to begin with — the site's two <details>.
  const [openOs, setOpenOs] = useState(null)     // null | 'ios' | 'android'
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
          <Image source={PHOTO} style={s.photo}
                 accessibilityLabel="Paul Wiens" resizeMode="cover" />
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
          <Title>Add to your home screen</Title>
          <Muted>
            Upset Alert also runs in your browser — there is nothing to download. Add it to
            your home screen and it opens full screen like any other app, keeps you signed
            in, and can notify you the moment a draw is released.
          </Muted>
          <Steps os="iPhone & iPad" meta="Safari" open={openOs === 'ios'}
                 onToggle={() => setOpenOs(o => (o === 'ios' ? null : 'ios'))}>
            <Step n={1}>
              Tap the <Text style={s.b}>•••</Text> button at the <Text style={s.b}>bottom</Text> of
              the screen. Don’t see the bar? Scroll up, or tap the very bottom once to bring it back.
            </Step>
            <Shot src="safari-more" w={660} h={198}
                  alt="Safari’s bottom bar, with the ••• button at its right end ringed" />
            <Step n={2}>Tap <Text style={s.b}>“Share”</Text> at the top of that menu.</Step>
            <Shot src="safari-share" w={660} h={416}
                  alt="Safari’s menu, with Share at the top ringed" />
            <Step n={3}>
              Scroll down that list and tap <Text style={s.b}>“Add to Home Screen”</Text>.
            </Step>
            <Shot src="add-to-home" w={660} h={675}
                  alt="The share sheet scrolled down, with Add to Home Screen ringed" />
            <Step n={4}>
              Tap <Text style={s.b}>“Add”</Text>, top right. Upset Alert is now an icon on your
              Home Screen — open it from there.
            </Step>
            <Text style={s.note}>
              Using Chrome on your iPhone? Tap the Share button inside the address bar at the{' '}
              <Text style={s.b}>top</Text> of the screen, then <Text style={s.b}>“Add to Home
              Screen”</Text>. Links opened inside another app — WhatsApp, Instagram, Facebook —
              can’t add anything: choose <Text style={s.b}>“Open in Safari”</Text> from that
              app’s menu first.
            </Text>
          </Steps>
          <Steps os="Android" meta="Chrome" open={openOs === 'android'}
                 onToggle={() => setOpenOs(o => (o === 'android' ? null : 'android'))}>
            <Step n={1}>Tap the <Text style={s.b}>⋮</Text> menu in the top right.</Step>
            <Step n={2}>
              Tap <Text style={s.b}>“Install app”</Text> — some phones say{' '}
              <Text style={s.b}>“Add to Home screen”</Text>.
            </Step>
            <Step n={3}>
              Tap <Text style={s.b}>“Install”</Text> to confirm. Upset Alert is now an icon on
              your home screen.
            </Step>
            <Text style={s.note}>
              Some phones offer the same thing as a banner at the bottom of the screen the first
              time you visit. Either way gets you the same app.
            </Text>
          </Steps>
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

  // 2:3, the shape the site's card crops to.
  photo: { width: '100%', aspectRatio: 2 / 3, maxHeight: 320, borderRadius: 12,
           backgroundColor: C.raised, marginBottom: S.sm },

  acc: { borderWidth: 1, borderColor: C.border, borderRadius: 12,
         backgroundColor: C.raised, overflow: 'hidden', marginTop: S.xs },
  accHead: { flexDirection: 'row', alignItems: 'center', gap: 8,
             paddingHorizontal: 14, paddingVertical: 12 },
  accOs: { ...T.smallMed, color: C.ink, letterSpacing: 0.5, textTransform: 'uppercase' },
  accMeta: { ...T.tiny, color: C.muted },
  accChev: { marginLeft: 'auto', color: C.muted, fontSize: 17, lineHeight: leading(18) },
  accBody: { paddingHorizontal: 14, paddingBottom: 14, gap: 8 },
  step: { flexDirection: 'row', gap: 8 },
  stepNum: { ...T.small, color: C.muted, width: 16, textAlign: 'right' },
  stepText: { ...T.small, color: C.inkBody, flex: 1 },
  b: { color: C.ink, fontFamily: 'Archivo_700Bold' },
  // Framed and held to a phone's width: these are screenshots of a DIFFERENT
  // interface than the one the reader is sitting in.
  shotWrap: { width: '100%', alignSelf: 'stretch' },
  shot: { borderRadius: 8, borderWidth: 1, borderColor: C.border },
  note: { ...T.tiny, color: C.muted, lineHeight: leading(17), marginTop: 4 },
})
