/*
 * Tests for the two comparisons that decide what the app SAYS.
 *
 * There is no test runner in this project yet and adding one is not worth it
 * for two pure functions, so this is a plain node script:
 *
 *     node scoring.test.mjs
 *
 * scoring.js is ESM but package.json is not type:module (React Native uses
 * babel), so it is loaded through a data: URL rather than renamed.
 */

import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
// `Buffer` below is a node global, and the project's eslint config is aimed at
// React Native — it has no node environment, so linting this file reported an
// undefined name. Imported explicitly rather than declared in the config: it
// is one file, and an import is the thing that is actually true.
import { Buffer } from 'node:buffer'

const src = readFileSync(new URL('./scoring.js', import.meta.url), 'utf8')
const { competitionRanks, sameStanding, slotLabel, pct, placesDecided, scrubEntries, tiebreakVisible, worldEntries } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

let n = 0
const check = (name, fn) => { fn(); n++; console.log('  ok  ' + name) }

check('ties share a rank and the next rank skips', () => {
  const e = [
    { total: 10, round_points: [4, 6] },
    { total: 10, round_points: [4, 6] },
    { total: 10, round_points: [4, 6] },
    { total: 5,  round_points: [5, 0] },
  ]
  assert.deepEqual(competitionRanks(e), [1, 1, 1, 4])
})

check('same total is a tie whatever the rounds say; the final guesses separate it', () => {
  // THE TIEBREAK IS THE FINAL (owner, 2026-09-18): level on points is level
  // until the final is played, when the closest guess on the champion's
  // aces, then on minutes, separates them; a bracket that never answered
  // sits below the answered ones it is level with.
  const e = [
    { total: 10, round_points: [0, 10] },
    { total: 10, round_points: [10, 0] },
  ]
  assert.equal(sameStanding(e[0], e[1]), true)
  assert.deepEqual(competitionRanks(e), [1, 1])
  const played = [
    { total: 10, tie_aces_diff: 1, tie_minutes_diff: 5 },
    { total: 10, tie_aces_diff: 1, tie_minutes_diff: 5 },
    { total: 10, tie_aces_diff: 1, tie_minutes_diff: 20 },
    { total: 10 },
  ]
  assert.equal(sameStanding(played[0], played[1]), true)
  assert.equal(sameStanding(played[1], played[2]), false)
  assert.equal(sameStanding(played[2], played[3]), false)
  assert.deepEqual(competitionRanks(played), [1, 1, 3, 4])
})

check('a lone entry ranks first, and an empty list is empty', () => {
  assert.deepEqual(competitionRanks([{ total: 3, round_points: [3] }]), [1])
  assert.deepEqual(competitionRanks([]), [])
})

check('a bye still shows the player who received it', () => {
  const m = { is_bye: true }
  assert.equal(slotLabel({ name: 'Sinner', seed: 1 }, m), 'Sinner')
  assert.equal(slotLabel(null, m), 'Bye')
})

check('an empty slot in a normal match is TBD, not a bye', () => {
  assert.equal(slotLabel(null, { is_bye: false }), 'TBD')
})

check('an unnamed qualifier slot reads Qualifier', () => {
  assert.equal(slotLabel({ entry_type: 'Q', name: '' }, { is_bye: false }), 'Qualifier')
  // Once the qualifier is known, the name wins.
  assert.equal(slotLabel({ entry_type: 'Q', name: 'Nardi' }, { is_bye: false }), 'Nardi')
})

check('a chance reads the way a person would say it', () => {
  // The two ends are the point: something that can still happen never prints
  // as 0%, and something already certain never prints as >99%.
  assert.equal(pct(1), '100%')
  assert.equal(pct(0.9996), '>99%')
  assert.equal(pct(0.0001), '<1%')
  assert.equal(pct(0), '0%')
  assert.equal(pct(0.41), '41%')
  assert.equal(pct(null), '–')
})

check('the chances follow the slider, with the range', () => {
  const entries = [{ user_id: 1, total: 0, correct_count: 0, round_points: [0, 0] },
                   { user_id: 2, total: 0, correct_count: 0, round_points: [0, 0] }]
  const timeline = [{ id: 11, round_number: 1, points: 2, winner_id: 7 }]
  const preds = { 1: { 11: 7 }, 2: { 11: 8 } }
  // Four numbers per row, as the server now sends them.
  const hist = { 1: { 1: [1, 1, 0.75, 1], 2: [2, 2, 0.25, 1] } }
  const rows = scrubEntries(entries, timeline, 1, preds, hist)
  assert.equal(rows[0].p_win, 0.75)
  assert.equal(rows[0].p_podium, 1)
  assert.equal(rows[1].p_win, 0.25)
  // A payload with only the range still works, and says nothing rather than 0.
  const old = scrubEntries(entries, timeline, 1, preds, { 1: { 1: [1, 1], 2: [2, 2] } })
  assert.equal(old[0].p_win, null)
})

check('rewound past the range, the chances come from their own request', () => {
  /* The history stops fifteen undecided matches out; earlier positions are
     fetched one at a time. Those figures fill the two chance columns while the
     range stays empty, because a sample understates an extreme. */
  const entries = [{ user_id: 1, total: 0, correct_count: 0, round_points: [0, 0] },
                   { user_id: 2, total: 0, correct_count: 0, round_points: [0, 0] }]
  const timeline = [{ id: 11, round_number: 1, points: 2, winner_id: 7 }]
  const preds = { 1: { 11: 7 }, 2: { 11: 8 } }
  const fetched = { 1: [0.6, 0.9], 2: [0.4, 0.8] }
  const rows = scrubEntries(entries, timeline, 1, preds, {}, fetched)
  assert.equal(rows[0].p_win, 0.6)
  assert.equal(rows[0].p_podium, 0.9)
  assert.equal(rows[0].best_rank, null)          // no range this early
  assert.equal(rows[0].podium_locked, false)
  // The history WINS where it has the position: it is the exact answer.
  const both = scrubEntries(entries, timeline, 1, preds,
                            { 1: { 1: [1, 1, 0.75, 1], 2: [2, 2, 0.25, 1] } }, fetched)
  assert.equal(both[0].p_win, 0.75)
  assert.equal(both[0].best_rank, 1)
  // Nothing fetched yet: a dash, not a zero.
  assert.equal(scrubEntries(entries, timeline, 1, preds, {}, null)[0].p_win, null)
})

check('a chosen world is certainties, not chances', () => {
  const entries = [{ user_id: 1, total: 10, correct_count: 1, round_points: [10, 0] },
                   { user_id: 2, total: 4, correct_count: 1, round_points: [4, 0] },
                   { user_id: 3, total: 0, correct_count: 0, round_points: [0, 0] },
                   { user_id: 4, total: 0, correct_count: 0, round_points: [0, 0] }]
  const world = { results: [{ match_id: 9, round_number: 2, points: 6, winner_id: 7 }] }
  const wp = { 1: { 9: 8 }, 2: { 9: 7 }, 3: { 9: 7 }, 4: { 9: 8 } }
  const rows = worldEntries(entries, world, wp)
  for (const r of rows) {
    assert.ok(r.p_win === 1 || r.p_win === 0)
    assert.equal(r.p_win, r.best_rank === 1 ? 1 : 0)
    assert.equal(r.p_podium, r.best_rank <= 3 ? 1 : 0)
  }
  // 1 and 2 finish level on 10 and share first (the final's tiebreak is
  // unknown in a chosen world, owner 2026-09-18): two winners, not one.
  assert.equal(rows.filter(r => r.p_win === 1).length, 2)
})


check('a medal needs a decided final AND the present', () => {
  /* The owner's report: a finished Washington Open scrubbed back to 7 of 31
     matches showed two trophies. `status` describes the draw in reality, so it
     stays 'completed' however far back the slider goes. */
  assert.equal(placesDecided({ status: 'completed', scrubbing: false }), true)
  assert.equal(placesDecided({ status: 'completed', scrubbing: true }), false)
  // Mid-tournament, at the far right: still no podium — nothing is decided.
  assert.equal(placesDecided({ status: 'active', scrubbing: false }), false)
  // A chosen what-if world HAS played its final, and choosing one drops the
  // slider, so its medals stand.
  assert.equal(placesDecided({ status: 'active', scrubbing: false, world: { results: [] } }), true)
  // Called with nothing at all (a screen before its data lands) must not throw.
  assert.equal(placesDecided(), false)
  assert.equal(placesDecided({}), false)
})

check('a bot takes no place and consumes none', () => {
  /* Highest_Rank held 8th on the US Open's global standings, so every person
     below it read one place lower than they stood. It stays in the table,
     sorted on points like everyone else; it just has no number. */
  const rows = [
    { user_id: 1, total: 209, round_points: [209] },
    { user_id: 2, total: 192, round_points: [192] },
    { user_id: 17, total: 166, round_points: [166], is_bot: true },
    { user_id: 3, total: 165, round_points: [165] },
  ]
  assert.deepEqual(competitionRanks(rows), [1, 2, null, 3])
})

check('a bot between two level people does not break their shared rank', () => {
  const rows = [
    { user_id: 1, total: 100, round_points: [100] },
    { user_id: 17, total: 100, round_points: [100], is_bot: true },
    { user_id: 2, total: 100, round_points: [100] },
    { user_id: 3, total: 90, round_points: [90] },
  ]
  // The two people are level: 1 and 1, then the next takes third.
  assert.deepEqual(competitionRanks(rows), [1, null, 1, 3])
})

check('a table of nothing but bots numbers nobody', () => {
  assert.deepEqual(competitionRanks([{ user_id: 17, total: 5, round_points: [5], is_bot: true }]), [null])
  assert.deepEqual(competitionRanks([]), [])
  assert.deepEqual(competitionRanks(null), [])
})

console.log(`\n  ${n} passed`)


// worldEntries: a bot has no place and no chance in a chosen world, and consumes none (owner, 2026-09-18).
{
  const entries = [
    { user_id: 1, username: 'Tono', total: 27, round_points: [27], correct_count: 5, is_bot: false },
    { user_id: 9, username: 'Highest_Rank', total: 27, round_points: [27], correct_count: 5, is_bot: true },
    { user_id: 2, username: 'dogger27', total: 26, round_points: [26], correct_count: 4, is_bot: false },
  ]
  const got = worldEntries(entries, { results: [] }, {})
  const by = Object.fromEntries(got.map(e => [e.user_id, e]))
  assert.equal(by[1].best_rank, 1); assert.equal(by[1].p_win, 1)
  assert.equal(by[9].best_rank, null); assert.equal(by[9].p_win, null); assert.equal(by[9].p_podium, null); assert.equal(by[9].podium_locked, false)
  assert.equal(by[2].best_rank, 2)
}


check('the tiebreak stays hidden until a draw is open for picks', () => {
  // Owner, 2026-09-18: nothing until next week's draw start. A locked draw
  // with no answer shows nothing; an open one asks; an answered one reads back.
  assert.equal(tiebreakVisible(null), false)
  assert.equal(tiebreakVisible({ locked: true, guess: null }), false)
  assert.equal(tiebreakVisible({ locked: false, guess: null }), true)
  assert.equal(tiebreakVisible({ locked: true, guess: { final_aces: 6, final_duration_min: 95 } }), true)
})
