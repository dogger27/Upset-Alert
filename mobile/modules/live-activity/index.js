/*
 * The JS face of the ActivityKit bridge.
 *
 * Loaded defensively for the same reason expo-notifications is: this is a
 * native module, and a build cut before it existed does not contain it. A
 * top-level import that throws takes the whole app down — which has already
 * happened once in this project.
 */

import { NativeModulesProxy, EventEmitter } from 'expo-modules-core'

let native = null
try {
  native = NativeModulesProxy?.LiveActivity ?? null
} catch {
  native = null
}

export const isAvailable = () => !!native

/** { supported, enabled, pushToStart } — or all false where unavailable. */
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

const emitter = native ? new EventEmitter(native) : null

export function addListener(event, handler) {
  if (!emitter) return { remove() {} }
  return emitter.addListener(event, handler)
}
