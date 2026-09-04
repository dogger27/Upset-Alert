/*
 * Wiring the ActivityKit bridge to the server.
 *
 * Started after sign-in, because every token here is meaningless until there
 * is a user to attach it to.
 *
 * BOTH TOKENS ARE OBSERVED, NEVER FETCHED ONCE. iOS reissues them without
 * warning — the push-to-start token periodically, and an activity's own token
 * mid-activity — and a token the server holds after it has been reissued is
 * simply dead. The endpoints upsert for that reason, so re-posting is the
 * expected path rather than an error case.
 */

import {
  addListener, attributesType, capabilities, isAvailable, runningActivities,
  startActivity, startListening,
} from './modules/live-activity'
import { useCallback, useEffect, useState } from 'react'
import { useFocusEffect } from 'expo-router'
import { getInstallId } from './install'
import { endActivity, getOffer, listActivities, registerActivity, registerPushToStart } from './api'

let started = false
const subs = []

export async function startLiveActivityBridge(contentVersion = 1) {
  if (started) return { ok: true, note: 'already running' }
  if (!isAvailable()) return { ok: false, note: 'module not in this build' }

  const caps = capabilities()
  if (!caps.supported) return { ok: false, note: 'iOS too old for Live Activities' }
  // areActivitiesEnabled is a per-app user setting. Worth reporting rather
  // than silently doing nothing: "you turned them off" is a different problem
  // from "we cannot".
  if (!caps.enabled) return { ok: false, note: 'Live Activities disabled in Settings', caps }

  const install_id = await getInstallId()
  const attributes_type = attributesType()

  subs.push(addListener('onPushToStartToken', ({ token }) => {
    if (!token || !attributes_type) return
    registerPushToStart(install_id, attributes_type, token)
      .catch(e => console.warn('[LA] push-to-start register failed:', e.message))
  }))

  subs.push(addListener('onActivityToken', ({ activityId, matchId, token }) => {
    if (!token || !activityId) return
    registerActivity({
      install_id,
      activity_id: activityId,
      push_token: token,
      match_id: matchId ?? null,
      content_version: contentVersion,
      // The server started it; the client is only reporting the token it was
      // handed. Recording that honestly matters for working out later why an
      // activity exists at all.
      started_by: 'push_to_start',
    }).catch(e => console.warn('[LA] activity register failed:', e.message))
  }))

  await startListening()
  started = true

  // Not awaited: reconciliation is housekeeping, and a Lock Screen that works
  // must not wait on it.
  reconcile(install_id, contentVersion)
    .catch(e => console.warn('[LA] reconcile failed:', e.message))

  return { ok: true, caps, attributes_type }
}

/* Put the server's view and the device's back in step.
 *
 * Both sides go stale in ways the other cannot see. The app is killed without
 * calling DELETE; the user swipes an activity away; a new build replaces the
 * one that owned it — which is exactly what happened on the first install of
 * the dashboard build, leaving a row the dispatcher would have pushed at
 * forever.
 *
 * Deletions only. A running activity the server does not know about is NOT
 * re-registered here, because its push token belongs to a registration we no
 * longer have and posting a placeholder would create a row the dispatcher
 * cannot use. pushTokenUpdates yields for every running activity when the
 * listener starts, and that path registers it properly.
 */
async function reconcile(install_id, contentVersion) {
  const onDevice = new Set(runningActivities().map(a => a.activityId))
  const { activities = [] } = (await listActivities()) || {}
  const stale = activities.filter(a => !onDevice.has(a.activity_id))
  for (const a of stale) {
    await endActivity(a.activity_id)
      .catch(e => console.warn('[LA] could not end', a.activity_id, e.message))
  }
  if (stale.length) console.log(`[LA] reconciled: ended ${stale.length} stale`)
  return { onDevice: onDevice.size, ended: stale.length }
}

/* Is THIS match already on the Lock Screen?
 *
 * The button used to be driven by a local `shown` flag, which is wrong twice
 * over: it resets on every reload, and it never knew about an activity started
 * before this render — including one started by a previous install. So the app
 * offered to show something that was already showing.
 *
 * ActivityKit is the only thing that actually knows, so ask it. Re-asked when
 * the screen regains focus (the user may have swiped the activity away while
 * looking at the Lock Screen) and whenever one ends.
 */
export function useShowingOnLockScreen(matchId) {
  const [showing, setShowing] = useState(false)

  const check = useCallback(() => {
    if (matchId == null) { setShowing(false); return }
    const found = runningActivities().some(a => Number(a.matchId) === Number(matchId))
    setShowing(found)
  }, [matchId])

  useEffect(() => {
    check()
    const sub = addListener('onActivityEnded', check)
    return () => { try { sub.remove() } catch { /* already gone */ } }
  }, [check])

  // Coming back from the Lock Screen is exactly when this can have changed.
  useFocusEffect(useCallback(() => { check() }, [check]))

  return [showing, check]
}

export function liveActivityStarted() { return started }

/* Put a match on the Lock Screen.
 *
 * The activity is created FIRST and registered with the server second, in that
 * order and not the other way round: ActivityKit is the thing that can refuse
 * (Live Activities disabled, too many running, iOS too old), and registering a
 * row for an activity that was never created leaves the dispatcher pushing at
 * an id that does not exist.
 *
 * The push token does not arrive with the activity — it comes later on
 * pushTokenUpdates, which the bridge is already listening for and which posts
 * to the same endpoint. So this registration is the row, and that listener
 * fills in the token that makes it updatable.
 */
export async function showOnLockScreen(offerMatch, contentVersion = 1) {
  const { attributes, content_state: state, match_id } = offerMatch || {}
  if (!attributes || !state) {
    throw new Error('This match cannot be shown yet — the server sent no activity payload')
  }
  const activityId = await startActivity(attributes, state)
  const install_id = await getInstallId()
  await registerActivity({
    install_id,
    activity_id: activityId,
    // A placeholder until pushTokenUpdates yields the real one; the endpoint
    // upserts on (device, activity_id), so the listener overwrites this.
    push_token: 'pending',
    match_id: match_id ?? null,
    content_version: contentVersion,
    started_by: 'client',
  })
  return activityId
}

/* THE USER CHOOSES. Any live singles match can go on the Lock Screen from
   its row; the server's offer endpoint validates the choice (it must be live
   and have a payload) and hands back the same attributes and state the
   automatic offer would. A few at a time: iOS stacks them, but the update
   budget is per activity and a Lock Screen of five cards is not a Lock
   Screen anyone reads. */
export const MAX_LOCK_SCREEN = 3

export function lockScreenCount() {
  return runningActivities().length
}

export async function showMatchOnLockScreen(matchId, contentVersion = 1) {
  if (runningActivities().some(a => Number(a.matchId) === Number(matchId))) return 'already'
  if (lockScreenCount() >= MAX_LOCK_SCREEN) {
    throw new Error(`Up to ${MAX_LOCK_SCREEN} matches at a time — remove one first`)
  }
  const offer = await getOffer(matchId)
  if (!offer?.match) throw new Error(offer?.reason || 'This match cannot be shown right now')
  return showOnLockScreen(offer.match, contentVersion)
}

/* Take a match off the Lock Screen. The native end is immediate where this
   build has it; the server's DELETE also sends an end push, which is what
   removes the card on builds that do not. Both are asked, so the card goes
   whichever answers first. */
export async function hideFromLockScreen(matchId) {
  const { endActivity: endNative } = await import('./modules/live-activity')
  const mine = runningActivities().filter(a => Number(a.matchId) === Number(matchId))
  for (const a of mine) {
    try { await endNative(a.activityId) } catch { /* older build */ }
    await endActivity(a.activityId).catch(e => console.warn('[LA] server end failed:', e.message))
  }
  return mine.length
}

export async function stopLiveActivityBridge() {
  for (const s of subs.splice(0)) {
    try { s.remove() } catch { /* already gone */ }
  }
  started = false
  const { stopListening, endAll } = await import('./modules/live-activity')
  // Sign-out ends them: a Lock Screen belonging to an account nobody is signed
  // into has no business still updating.
  try { await stopListening() } catch { /* no module */ }
  try { await endAll() } catch { /* no module */ }
}
