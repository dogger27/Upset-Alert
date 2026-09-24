/* TODAY, AS STATE — the device's calendar date, and a re-render when it turns.
 *
 * The schedule is a TAB: it stays mounted for as long as the app lives, which
 * on a phone is days. Anything that read the date once — a memo keyed only on
 * the server's answer — kept yesterday's "T" on the strip after midnight while
 * the slot beside it, which read the clock on every render, said "Today" over
 * the next chip (owner's screenshot, 2026-09-24). One value, owned here, that
 * every reader takes and every memo keys on, so they cannot disagree.
 *
 * It turns at the next local midnight (a timer), and is re-read whenever the
 * app comes back to the foreground, because iOS does not run a suspended
 * app's timers — the phone that sat in a pocket overnight fires nothing. */
import { useEffect, useState } from 'react'
import { AppState } from 'react-native'
import { msToMidnight, todayIso } from './dayLabels.js'

export function useToday() {
  const [today, setToday] = useState(todayIso)
  useEffect(() => {
    let timer
    const arm = () => {
      clearTimeout(timer)
      timer = setTimeout(() => { setToday(todayIso()); arm() }, msToMidnight())
    }
    arm()
    const sub = AppState.addEventListener('change', st => {
      if (st === 'active') { setToday(todayIso()); arm() }
    })
    return () => { clearTimeout(timer); sub.remove() }
  }, [])
  return today
}
