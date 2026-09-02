/*
 * The hamburger: the site's primary nav collapsed into a menu, minus what the
 * tab bar already carries (Dashboard, Leagues, Schedule). Draw History, Hall
 * of Fame, Rules and About used to be reached from tiles on the Leagues tab
 * and a link at the foot of Status — places they had no business being.
 */
import { useRouter } from 'expo-router'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { Sheet } from './sheet'
import { C, R, S, T } from './theme'

const ITEMS = [
  { href: '/history',      label: 'Draw History', sub: 'Every draw you’ve played',    icon: 'time-outline' },
  { href: '/hall-of-fame', label: 'Hall of Fame', sub: 'Best ever performances',      icon: 'trophy-outline' },
  { href: '/rules',        label: 'Rules',        sub: 'How picks score, tier by tier', icon: 'book-outline' },
  { href: '/about',        label: 'About',        sub: 'Upset Alert, and where its data comes from', icon: 'information-circle-outline' },
]

export function MenuSheet({ visible, onClose }) {
  const router = useRouter()
  return (
    <Sheet visible={visible} onClose={onClose}>
      <View style={s.list}>
        {ITEMS.map(it => (
          <Pressable key={it.href} onPress={() => { onClose(); router.push(it.href) }}
                     style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}
                     accessibilityRole="link" accessibilityLabel={it.label}>
            <View style={s.icon}><Ionicons name={it.icon} size={20} color={C.greenLit} /></View>
            <View style={{ flex: 1 }}>
              <Text style={s.label}>{it.label}</Text>
              <Text style={s.sub} numberOfLines={1}>{it.sub}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={C.faint} />
          </Pressable>
        ))}
      </View>
    </Sheet>
  )
}

const s = StyleSheet.create({
  list: { gap: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: S.md, paddingVertical: S.sm, paddingHorizontal: S.xs, borderRadius: R.md },
  icon: { width: 36, height: 36, borderRadius: 18, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center' },
  label: { ...T.bodyMed, color: C.ink },
  sub: { ...T.tiny, color: C.faint },
})
