/*
 * The JS face of the ActivityKit bridge.
 *
 * requireOptionalNativeModule, NOT NativeModulesProxy. The proxy is the legacy
 * accessor and does not see modules defined with the modern `Module` API —
 * which LiveActivityModule is — so it returned undefined even in a build that
 * genuinely contained the module, and the bridge reported "module not in this
 * build" while sitting right next to it.
 *
 * The "optional" variant returns null instead of throwing when the module is
 * absent, which is the defensive load this file needs anyway: a build cut
 * before the module existed does not contain it, and a top-level import that
 * throws takes the whole app down.
 */

import { requireOptionalNativeModule } from 'expo-modules-core'

const native = requireOptionalNativeModule('LiveActivity')

export const isAvailable = () => !!native

/** { supported, enabled, pushToStart } — all false where unavailable. */
export function capabilities() {
  if (!native) return { supported: false, enabled: false, pushToStart: false }
  try {
    return native.capabilities()
  } catch {
    return { supported: false, enabled: false, pushToStart: false }
  }
}

/** The Swift struct name; the server echoes it as `attributes-type`. */
export function attributesType() {
  if (!native) return null
  try {
    return native.attributesType()
  } catch {
    return null
  }
}

export async function startListening() {
  if (native) await native.startListening()
}

export async function stopListening() {
  if (native) await native.stopListening()
}

export async function endAll() {
  if (native) await native.endAll()
}

/* A modern Expo module IS an event emitter — no separate EventEmitter to
   construct. Returns an inert subscription when there is no module, so callers
   never have to null-check before removing one. */
export function addListener(event, handler) {
  if (!native?.addListener) return { remove() {} }
  return native.addListener(event, handler)
}
