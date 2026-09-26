/* ADMIN, ON THE APP (owner, 2026-09-26). The two things worth checking from a
   phone are native: the Sofascore request ledger and the system log. The
   rest of the site's admin (users, tournaments, players, rankings, settings)
   is desk work and opens on the website. Reached from the menu, which offers
   it only to admins; the server refuses these screens' data to anyone else. */
import { useRouter } from 'expo-router'
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useAuth } from '../../../../auth'
import { C, R, S, T } from '../../../../theme'
import { Muted, Screen } from '../../../../ui'

const SITE_ADMIN = 'https://upsetalert.ca/admin'

const ITEMS = [
  { href: '/admin/sofascore', label: 'Data requests', sub: 'Sofascore, protennislive, Tennis Explorer: blocked or not, the rate, who is asking', icon: 'pulse-outline' },
  { href: '/admin/logs', label: 'System log', sub: 'Errors and warnings, one row per problem', icon: 'list-outline' },
  { url: SITE_ADMIN, label: 'Everything else, on the website', sub: 'Users, tournaments, players, rankings, settings', icon: 'open-outline' },
]

export default function AdminHome() {
  const router = useRouter()
  const { me } = useAuth()
  if (!me?.is_admin) {
    return <Screen><Muted>This page is for admins.</Muted></Screen>
  }
  return (
    <Screen>
      <View style={s.list}>
        {ITEMS.map(it => (
          <Pressable key={it.label}
                     onPress={() => (it.url ? Linking.openURL(it.url) : router.push(it.href))}
                     style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}
                     accessibilityRole="link" accessibilityLabel={it.label}>
            <View style={s.icon}><Ionicons name={it.icon} size={20} color={C.greenLit} /></View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>{it.label}</Text>
              <Text style={s.sub}>{it.sub}</Text>
            </View>
            <Ionicons name={it.url ? 'open-outline' : 'chevron-forward'} size={16} color={C.faint} />
          </Pressable>
        ))}
      </View>
    </Screen>
  )
}

const s = StyleSheet.create({
  list: { gap: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: S.md, paddingVertical: S.md, paddingHorizontal: S.sm,
         borderRadius: R.md, backgroundColor: C.card, borderWidth: 1, borderColor: C.border },
  icon: { width: 36, height: 36, borderRadius: 18, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center' },
  label: { ...T.bodyMed, color: C.ink },
  sub: { ...T.tiny, color: C.faint },
})
