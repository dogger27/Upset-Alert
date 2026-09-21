/*
 * Renaming a tournament has to refresh the caches that NAME it.
 *
 *     node rename.test.mjs
 *
 * useApi's invalidate() matches by PREFIX. The tournament rename sheet
 * invalidated 'schedule:' alone, and the SHORT name is read from the
 * tournaments list — whose cache key is 'tournaments', which does not begin
 * with 'schedule:'. So a rename showed up in the day's headings and nowhere
 * else until the app restarted: not in the Schedule's filter pills, not in the
 * tab bar's chooser, not on the draw screens (owner, 2026-09-21).
 *
 * A source check rather than a render: the bug is which strings are passed to
 * one function, there is no return value to inspect, and a renderer would test
 * React rather than the wiring.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const SRC = readFileSync(new URL('./rename.jsx', import.meta.url), 'utf8')

/** The body of the named component, up to the next top-level export. */
function componentBody(name) {
  const at = SRC.indexOf(`export function ${name}`)
  assert.notEqual(at, -1, `${name} is gone — has it been renamed?`)
  const next = SRC.indexOf('\nexport function ', at + 1)
  return SRC.slice(at, next === -1 ? SRC.length : next)
}

test('renaming a TOURNAMENT refreshes both caches that name it', () => {
  const body = componentBody('TournamentRenameSheet')
  assert.match(body, /invalidate\(\s*'schedule:'\s*\)/,
    'the day’s rows carry the shown name')
  assert.match(body, /invalidate\(\s*'tournaments'\s*\)/,
    'the tournaments LIST carries the short name the pills and chooser read')
})

test('renaming a COURT touches only the schedule', () => {
  // A court name exists nowhere but the day's rows, so widening this one would
  // be refetching the whole tournament list for nothing, every rename.
  const body = componentBody('CourtRenameSheet')
  assert.match(body, /invalidate\(\s*'schedule:'\s*\)/)
  assert.doesNotMatch(body, /invalidate\(\s*'tournaments'\s*\)/)
})

test('the prefixes are real keys, not guesses', () => {
  // invalidate() is a prefix match, so a typo silently invalidates nothing.
  // These are the keys the hooks actually register.
  const api = readFileSync(new URL('./useApi.js', import.meta.url), 'utf8')
  assert.match(api, /k\.startsWith\(prefix\)/, 'invalidate still matches by prefix')
  const choosable = readFileSync(new URL('./choosableTournaments.js', import.meta.url), 'utf8')
  assert.match(choosable, /useApi\(\s*ready \? 'tournaments'/,
    'the pills’ list is still cached under exactly "tournaments"')
})
