/*
 * The Schedule page's score card, extracted so the draw page's score-history
 * popup renders a match EXACTLY as the schedule does — same rows, same set
 * cells, same tick and cross, same serve ball, same name-fitting ladder.
 * Everything here moved VERBATIM from pages/Schedule.jsx; the behaviour of the
 * schedule page is unchanged by construction, and the sched-* styles stay in
 * Schedule.css (imported below) because that file's cascade is order-dependent
 * and splitting it invites regressions for zero benefit.
 */

import { Fragment, useLayoutEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import useFlashOnChange from '../hooks/useFlashOnChange'
import { nationalityIso2, splitPlayerName } from '../utils/flags'
import { rootFontPx, textWidth } from '../utils/text'
import { parseSet } from '../utils/score'
import '../pages/Schedule.css'

/* MEASURE THE COLUMN, DO NOT GUESS AT IT.
   Every version of this before now counted CHARACTERS against a tuned constant.
   That cannot work: "WWW" and "iii" are the same length and nothing like the
   same width, the column's width changes with the breakpoint, the flag, the
   serve ball, the point cell and how many sets are on the board — and
   .sched-competitor-name is overflow:visible, so the moment the guess is wrong
   by a few pixels the name paints straight over the ball and the score instead
   of being clipped. "VANDECASTEELE [8]" sitting on the tennis ball is what a
   wrong guess looks like.
   So the row reports the width it actually has, the text is measured on a
   canvas in the font it is actually drawn in, and the rung is chosen from those
   two numbers. No characters, no constants, no breakpoint assumptions.
   It cannot oscillate: .sched-competitor-name is flex:1 1 auto with min-width:0
   among fixed-width siblings, so its width is decided by THEM. Making the name
   inside it narrower does not widen the box, so a smaller name cannot feed back
   into a new measurement. */

// Pixels held back from the measured name box: canvas text measurement and
// the browser's own rendering disagree by a hair, and an unclipped name pays
// for that by overflowing onto the serve ball beside it.
const NAME_SAFETY = 6


function useNameBox() {
  const ref = useRef(null)
  const [box, setBox] = useState(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const measure = () => {
      const cs = getComputedStyle(el)
      const px = parseFloat(cs.fontSize) || rootFontPx()
      const w = el.clientWidth
      if (w > 0) setBox(prev => (prev && prev.avail === w && prev.fontPx === px)
        ? prev : { avail: w, fontPx: px })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, box]
}

/* Fallback only, for the first paint before the observer has reported. Kept
   deliberately generous so nothing shrinks and then springs back. */
const FIT_CHARS = 15

/* ...and that is the budget when the scores are there to compete with. A row
   that has not been played shows no set columns at all, which is most of the
   sheet the morning it is published, and the name was still being measured as
   though three sets sat beside it — so a name with room to spare was set
   smaller anyway. Each column the row does not render is handed back.
   Still a pure function of the data: nothing is measured, so there is nothing
   to oscillate, and CSS keeps the final say over whether any of it applies. */
const SET_SLOTS = 3
const SET_CHARS = 2

/* A round label that already announces qualifying, so the separate "Q" chip
   beside it would only repeat itself. */

const DOUBLES_FIT = 22

/* Roughly what one flag costs the line it sits on, in characters: the box is
   1.05rem plus its margin, against an average character of a bit under half
   that. Approximate on purpose — it decides between rungs of a ladder, not a
   pixel boundary. */
const FLAG_CHARS = 3

/* WHICH SIDES THE LADDER BELOW GOVERNS.
   An unresolved side offering a CHOICE is drawn by Side's alternatives branch,
   which fits itself and never reads `form` or `flags`. Every other side is
   written by the rungs. Stated once, and used by both, because the fit and the
   render have to mean the same sides — when they did not, the ladder was sized
   against a line the page never drew. See the call site in MatchScoreCard. */
function isAltSide(players, tbd) {
  return !!tbd && players.length > 1
}

/* HOW MUCH OF A DOUBLES TEAM FITS ON ITS LINE.
   A doubles side was always surnames and never a flag, whatever room the row
   had — "PITER / TJEN" against "JIANG / ZHANG [2]" on a card with two thirds of
   it empty, because a match that has not been played shows no set columns and
   nothing was claiming the space they leave.
   So: take the richest form that fits, flags first, then given names. Both
   sides are tested TOGETHER and get the same answer — deciding per side would
   put initials on one team and bare surnames on the other in the same match,
   which reads as a bug rather than as a fit. */
const DOUBLES_RUNGS = [
  ['full', true], ['initial', true], ['surname', true],
  ['full', false], ['initial', false], ['surname', false],
]

/** The team's seed: the sheet prints it against both partners, and it belongs
 *  to neither of them separately. */
function teamSeedOf(players) {
  return players.map(p => (p.seed != null ? `[${p.seed}]` : splitPlayerName(p.name).seed))
    .find(Boolean) ?? null
}

/** One partner, written as long as the chosen rung allows. */
function partnerText(raw, form) {
  const { first, last, members } = splitPlayerName(raw)
  // The "partner" may be a WHOLE TEAM: an unresolved doubles side names two
  // PAIRS, and each pair arrives as one printed string. Every rung applies to
  // each member, or the ladder would offer the same string at all three and a
  // line too long for the card would go straight to shrinking the type.
  if (members) return members.map(m => oneName(m, form)).join(' / ')
  return oneName({ first, last: last || raw }, form)
}

function oneName({ first, last }, form) {
  if (form === 'surname' || !first) return last
  return form === 'full' ? `${first} ${last}` : `${first.trim()[0]}. ${last}`
}

function doublesLineOf(players, form) {
  return players.map(p => partnerText(p.name, form)).join(' / ')
    + (teamSeedOf(players) ? ` ${teamSeedOf(players)}` : '')
}

/* What a doubles line gains from a set column the row does not render. More
   than the singles credit, because a doubles line is set at 0.78rem against the
   singles name's ~0.95 — the same freed pixels buy more characters. The extra
   two are the result mark, which disappears with the scores rather than
   separately: a tick only exists where there is a result. */
const DOUBLES_SET_CHARS = 3
const DOUBLES_MARK_CHARS = 2

function doublesPresentation(sides, sets, box = null) {
  /* MEASURED WHEN THE ROW HAS REPORTED ITS WIDTH, counted only before that.
     The singles ladder stopped guessing some time ago; this one was still
     comparing character counts to a constant, so a doubles line sat shrunk on a
     card with two thirds of it empty. Same reasoning as PlayerName: characters
     are not widths, and the column changes with the breakpoint and with how
     many score cells the row is showing. */
  if (box) {
    const rem = rootFontPx()
    const px = box.fontPx
    for (const [form, flags] of DOUBLES_RUNGS) {
      const fits = sides.every(players => {
        if (!players.length) return true
        const text = doublesLineOf(players, form)
        const flagPx = flags ? players.length * (1.05 + 0.3) * rem : 0
        return textWidth(text, px, 600) + flagPx + 2 <= box.avail
      })
      if (fits) return { form, flags }
    }
    return { form: 'surname', flags: false }
  }
  const fit = DOUBLES_FIT + Math.max(0, SET_SLOTS - sets) * DOUBLES_SET_CHARS
    + (sets === 0 ? DOUBLES_MARK_CHARS : 0)
  for (const [form, flags] of DOUBLES_RUNGS) {
    const fits = sides.every(players => !players.length || (
      doublesLineOf(players, form).length + (flags ? players.length * FLAG_CHARS : 0) <= fit))
    if (fits) return { form, flags }
  }
  // Nothing fits: the shortest form, and the existing scale takes it from here.
  return { form: 'surname', flags: false }
}

function PlayerName({ raw, surnameOnly, hideSeed, nationality, seed: seedProp, tight,
                     sets = SET_SLOTS, form, box = null, hasFlag = true }) {
  const { seed: printedSeed, first, last, nat, members } = splitPlayerName(raw)
  const isTeam = !!members
  // A seeding sent as a field beats one parsed out of the name: a resolved
  // player's name comes from the bracket and never carried brackets to parse.
  const seed = seedProp != null ? `[${seedProp}]` : printedSeed
  // Our own record wins over whatever the sheet printed: it drops the country
  // when space is tight, and a slot resolved from an "OR" carries the bracket's
  // name, which never had one inline.
  const iso2 = nationalityIso2(nationality || nat)

  /* Two forms of a singles name, and CSS picks. On a phone the name column is
     about 180px and a long one — "Amanda ANISIMOVA [9]" — ran under the result
     mark and the score. An initial is how a draw sheet prints a name it has no
     room for, and it still names the same person; a cut or shrunk one does not.
     Whether it fits depends on the width, which only CSS knows, so both forms
     are rendered and the breakpoint chooses. The length test is a pure function
     of the string — nothing is measured, so there is nothing to oscillate.
     THE SEED COUNTS. It is part of the same run of text — "Madison KEYS" fits
     and "Madison KEYS [20]" does not, and measuring the name alone let exactly
     that case through, with the seed sitting on top of the set score.
     15 characters is where the column runs out, flag and three sets included. */
  const full = [first, last].filter(Boolean).join(' ')
  const shown = full + (!hideSeed && seed ? ` ${seed}` : '')
  /* A LIVE row is narrower than a finished one. It spends width on the serve
     ball and on the point column, and the name is what pays for both — which is
     how the ball came to sit on top of "En-Shuo LIANG". Same ladder, two
     characters less to work with — three was a guess and it spent room the row
     did not need, leaving a visible gap between the name and the ball. The ball
     and the point cell are about two characters' worth between them. */
  const fit = FIT_CHARS + Math.max(0, SET_SLOTS - sets) * SET_CHARS - (tight ? 2 : 0)

  /* THE MEASURED BUDGET, in pixels, in the font this row actually draws in.
     Everything the name shares its box with is subtracted first: the flag and
     its gap, and the seed — a sibling at 0.85em that no character count ever
     included, which is precisely how "[8]" came to sit on the tennis ball.
     Two pixels are held back so a name never finishes flush against whatever
     follows it. `box` is null only on the very first paint, before the observer
     has reported; the character estimate still covers that one frame. */
  const px = box?.fontPx ?? 0
  const rem = rootFontPx()
  const seedText = !hideSeed && seed ? ` ${seed}` : ''
  /* THE SEED IS INSIDE WHAT SHRINKS, so it must not be reserved outside it.
     --name-scale goes on .sched-player, which contains the seed — the note on
     the ladder below says so in as many words ("the seed shrinks with the name
     it belongs to"). But the seed was ALSO subtracted from the box at full
     size before the ladder ever ran, so the row paid for it twice: once in the
     budget, once again in the rendering. On a completed US Open card
     "RINDERKNECH [26]" came out at 0.52 while "S. SHIMABUKURO" — a LONGER name
     on the same card, in the same box, differing only in having no seed — held
     0.78. The seed cost 30px of a 113px box, and 14 of them were spent on
     nothing.
     So the seed joins the thing it scales with: name and seed are measured
     together and solved for one scale, which is exact rather than circular —
     s·(name + seed) <= avail - flag - safety. The flag stays outside because
     it is sized in rem and does not scale. */
  const flagPx = box && hasFlag ? (1.05 + 0.3) * rem : 0
  const seedPx = box && seedText
    ? textWidth(seedText, px * 0.85, 700) + 0.28 * rem : 0
  const extras = box
    ? flagPx
      // A REAL GAP, not a rounding allowance. The name does not clip by
      // design, so a canvas measurement a few pixels under the rendered
      // width does not truncate — it overflows, and the serve ball sitting
      // immediately after the name is what it lands on ("C. BRANSTINE" with
      // the ball over the final letter). Six pixels covers the measurement
      // error and keeps the ball clear of the longest name.
      + NAME_SAFETY
    : 0
  const budget = box ? Math.max(0, box.avail - extras) : null
  // Every rung and the final scale measure the WHOLE run that shrinks — the
  // name and the seed it carries — against that budget.
  const wide = (text) => textWidth(text, px, 600) + seedPx
  /* The ladder is unchanged — full name, then an initial, then the surname
     alone, then size — but each rung is now accepted or rejected by MEASURING
     it rather than by counting its letters. */
  const fitsPx = (text) => budget == null || wide(text) <= budget
  /* `full`, not `shown`. `shown` has the seed spelled into the string, and
     wide() now adds the seed's own measurement on top — so testing it charged
     the row for the seed twice and sent names to the initialled rung that the
     full form would have held. It also made this test disagree with the one
     the ladder itself uses a few lines down, which is fitsPx(full); the two
     decide the same question and must give the same answer. */
  const longName = !surnameOnly && (budget != null ? !fitsPx(full) : shown.length > fit)
  const initialled = first ? `${first.trim()[0]}. ${last}` : last

  /* AND A RUNG BELOW THE INITIAL, because some surnames are longer than the
     column on their own. "Q. VANDECASTEELE [8]" is already the abbreviated
     form and still runs under the set scores — there is no shorter way to
     write it that still names the person, so the type has to give instead.
     Same order of sacrifice the draw page uses: full name, then an initial,
     then size. Never a truncation — a cut surname names nobody.
     Proportional to how far over it is, floored so it cannot shrink into
     illegibility chasing a name no width would have held. Applied to the whole
     player, so the seed shrinks with the name it belongs to rather than
     staying full size beside a smaller one; the flag is sized in rem and holds
     its own.
     Handed to CSS as a custom property rather than a font-size, because
     WHETHER to shrink is a question about width and only the stylesheet knows
     the width. A desktop card is three times this column and shows the full
     name anyway — shrinking there would be a regression bought for nothing.
     Same division of labour as the initial above: JS decides how much, the
     breakpoint decides whether. */
  /* THE RUNG THAT WAS MISSING. full -> "A. Bondar" -> "Bondar" -> shrink.
     Without the third, a long given name and a long surname together had only
     one step of relief and then a floor, and the pair ran straight over the
     score. The surname alone still names the person; a name over a score names
     nobody and hides the score as well. */
  const seedPart = seedText
  const lastOnly = last || full
  /* Same ladder as ever — full name, then an initial, then the surname alone,
     then size — but each rung is now accepted or rejected by MEASURING it
     rather than by counting its letters. */
  // A doubles side has already been fitted as a whole — both partners, the
  // slash and the team seed measured together, because no partner knows how
  // long the other is. That answer wins over anything decided here for one
  // name in isolation.
  const decided = form ? partnerText(raw, form) : null
  const tightest = decided ?? (surnameOnly
    ? last
    : budget != null
      ? (fitsPx(full) ? full : fitsPx(initialled) ? initialled : lastOnly)
      : (`${full}${seedPart}`.length <= fit ? `${full}${seedPart}`
         : `${initialled}${seedPart}`.length <= fit ? `${initialled}${seedPart}`
         : `${lastOnly}${seedPart}`))
  /* AND THEN IT SHRINKS AS FAR AS IT HAS TO. The floor is 0.45, which is small
     enough to be barely readable and is deliberately not a compromise: a name
     that overlaps the score has destroyed two pieces of information, and one
     unreadably small name has destroyed less than that. It is also nearly
     unreachable — by this rung the text is a bare surname, and a surname long
     enough to need half size is not a real one. */
  /* And then it shrinks by the ratio it is actually over by. The floor stays
     0.45 and stays nearly unreachable — by this rung the text is a bare
     surname. Below it a name would be illegible, and an illegible name that
     fits still beats a legible one sitting on top of the score. */
  const scale = decided
    // A doubles partner shares the box with the other one, the slash and the
    // team seed, so the whole LINE is fitted at once in Side() and carries the
    // scale on .sched-side. Measuring one partner against the full box here
    // would be measuring the wrong thing, and the two scales would compound.
    ? 1
    : budget != null
      ? (wide(tightest) > budget ? Math.max(0.45, budget / wide(tightest)) : 1)
      : (tightest.length > fit ? Math.max(0.45, fit / tightest.length) : 1)

  return (
    <span className="sched-player"
          style={scale < 1 ? { '--name-scale': scale } : undefined}>
      {/* A missing nationality here is not missing DATA — the tours list
          Russian and Belarusian players as neutral athletes with no flag, and
          the sheet omits it deliberately.
          Tennis Explorer does hold a country for them, and we deliberately do
          not use it: the official order of play withholds it on purpose.
          An OUTLINED EMPTY BOX rather than nothing at all. Drawing nothing let
          those names start a flag's width to the left of every other name in
          the column, which reads as a layout fault rather than as a country
          being withheld. The box says the same thing the sheet does — there is
          a flag's worth of nothing here — and keeps the column straight. */}
      {/* NOTHING AT ALL for a side that names a whole TEAM in one string. The
          blank box means "this player's country was withheld", and a pair has
          two countries and one box — so it would be saying something false,
          about a row where the sheet in fact printed both. Nor is there a
          column to keep straight: the alternatives beside it draw no flag
          either. (Winston-Salem 2026-08-26, "ARRIBAGE / GUINARD".) */}
      {iso2
        ? <span className={`fi fi-${iso2.toLowerCase()} sched-flag`} title={nat} />
        : isTeam
          ? null
          : <span className="sched-flag flag-blank" aria-hidden="true" />}
      <span className={clsx('sched-pname', { 'sched-pname--long': longName })}>
        {decided ?? (surnameOnly ? last : longName ? (
          <>
            <span className="sched-name-full">{full}</span>
            {/* The abbreviated form is whichever rung the scale above was
                computed against — an initial where that fits, the bare surname
                where it does not. Rendering the initial while having sized the
                surname is how a name ends up over the score. */}
            <span className="sched-name-abbr">
              {`${initialled}${seedPart}`.length <= fit ? initialled : lastOnly}
            </span>
          </>
        ) : full)}
        {/* AFTER the name. Leading it, the seed was the first thing on the line
            and pushed every name to a different starting column depending on
            whether it had one — so the names never formed an edge to scan. It
            also read as the more important fact, which it is not. */}
        {!hideSeed && seed && <span className="sched-seed">{seed}</span>}
      </span>
    </span>
  )
}

function Side({ players, doubles, tbd, tight, sets, form = 'surname', flags = false,
               box = null }) {
  if (!players.length) return <span className="sched-side">TBD</span>

  // An unresolved side is a choice between two whole teams, not a list of
  // players — "O. Luz / R. Matos OR C. Harrison / N. Skupski". Rendering it as
  // four names in a row says nothing about who partners whom. Each alternative
  // is already one entry, so they only need separating.
  if (isAltSide(players, tbd)) {
    /* AND IT IS FITTED LIKE EVERY OTHER LINE ON THIS CARD. This branch had no
       ladder at all — it drew at full size and let the text run — which held
       only while every alternative was a single surname ("CERUNDOLO or
       SURESH"). A doubles alternative is a whole pair, so the line is twice
       as long: "SCHNAITTER / WALLNER or LAMMONS / WITHROW" ran off the right
       edge of a 390px card on 2026-08-26 and the last name was cut in half.
       Same measured budget and same 0.72 floor as the doubles line below, and
       the media query decides whether it applies at all. */
    const altText = players.map(p => splitPlayerName(p.name).last || p.name).join(' or ')
    let altScale = 1
    if (box && box.avail > 0) {
      const need = textWidth(altText, box.fontPx, 600)
      if (need > box.avail - 2) altScale = Math.max(0.72, (box.avail - 2) / need)
    } else if (altText.length > DOUBLES_FIT) {
      altScale = Math.max(0.72, DOUBLES_FIT / altText.length)
    }
    return (
      <span className="sched-side sched-side--alt"
            style={altScale < 1 ? { '--name-scale': altScale } : undefined}>
        {players.map((p, i) => (
          <span key={i} className="sched-altteam">
            {i > 0 && <span className="sched-or">or</span>}
            {/* Surnames, singles or doubles. Two candidates and a separator
                have to fit the ONE line this side is given, and a slot that has
                not resolved is by definition the least important thing on the
                card — names neither of which may turn out to be playing.
                A doubles alternative is a whole team in one string, and it USED
                to be printed raw here on the grounds that a team has no surname
                to take. It does: splitPlayerName reads a "/" as two people and
                returns both surnames. Printing it raw was fine while only the
                WTA's abbreviated form reached this branch ("O. Luz / R. Matos")
                and broke the moment the ATP's did — "SCHNAITTER GER / WALLNER
                GER or [WC] LAMMONS USA / WITHROW USA" ran clean off the side of
                the card on a phone, seeds, countries and all. */}
            <span className="sched-pname">
              {splitPlayerName(p.name).last || p.name}
            </span>
          </span>
        ))}
      </span>
    )
  }
  // A doubles seed belongs to the TEAM. The sheet repeats it against both
  // partners, which reads as two separately-seeded players.
  const teamSeed = doubles ? teamSeedOf(players) : null

  /* A DOUBLES SIDE IS ONE LINE, and its budget is the whole line: two surnames,
     the slash between them, and the team seed. Scaled here rather than inside
     each PlayerName, because no player knows how long the other one is — and
     because the SEED is a sibling of both, so it was in nobody's budget at all.
     That is how "[2]" came to sit on top of the result mark. */
  const doublesLine = doubles ? doublesLineOf(players, form) : ''
  // Measured against the real column where we have it — see doublesPresentation.
  let teamScale = 1
  if (doubles && doublesLine) {
    if (box) {
      const rem = rootFontPx()
      const flagPx = flags ? players.length * (1.05 + 0.3) * rem : 0
      const budget = Math.max(0, box.avail - flagPx - NAME_SAFETY)
      const need = textWidth(doublesLine, box.fontPx, 600)
      if (need > budget && budget > 0) teamScale = Math.max(0.72, budget / need)
    } else if (doublesLine.length > DOUBLES_FIT) {
      teamScale = Math.max(0.72, DOUBLES_FIT / doublesLine.length)
    }
  }

  return (
    <span className={clsx('sched-side', { 'sched-side--flags': doubles && flags })}
          style={teamScale < 1 ? { '--name-scale': teamScale } : undefined}>
      {players.map((p, i) => (
        <Fragment key={`${p.side}${p.position}${i}`}>
          {/* Partners are separated by a slash, the way every draw sheet writes
              a pair. A bare space read as two unrelated names once the flags
              sat between them. */}
          {i > 0 && <span className="sched-slash">/</span>}
          <PlayerName raw={p.name} surnameOnly={doubles} hideSeed={doubles}
                      nationality={p.nationality} seed={p.seed} tight={tight}
                      sets={sets} form={doubles ? form : undefined}
                      box={box}
                      hasFlag={!doubles || flags} />
        </Fragment>
      ))}
      {/* Same placement as a singles seed, and for the same reason. */}
      {teamSeed && <span className="sched-seed sched-seed--team">{teamSeed}</span>}
    </span>
  )
}

function ServeBall() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" className="sched-ball" aria-label="serving">
      <circle cx="12" cy="12" r="11" fill="#7ba81f" />
      <g fill="none" stroke="#fff" strokeWidth="2">
        <path d="M12 1A12.04 12.04 0 0 1 1 12" />
        <path d="M12 23A12.04 12.04 0 0 1 23 12" />
      </g>
      <circle cx="12" cy="12" r="11" fill="none" stroke="#1b4332" strokeWidth="2" />
    </svg>
  )
}

function SetCell({ cell, bold }) {
  const { g, tb } = parseSet(cell)
  // Before the early return, not after — a games count that goes from a number
  // to nothing still has to run the hook. (See the note in Schedule.css on what
  // the flash is for.)
  const flash = useFlashOnChange(`${g}|${tb ?? ''}`)
  if (g === '' && tb == null) return <span className="sched-set empty">·</span>
  return (
    <span className={clsx('sched-set', { 'sched-set--won': bold, 'sched-score--bump': flash })}>
      {g}{tb != null && <sup>{tb}</sup>}
    </span>
  )
}

function PointCell({ point, tiebreak }) {
  const flash = useFlashOnChange(point)
  return (
    <span className={clsx('sched-point', { 'sched-point--tb': tiebreak,
                                           'sched-score--bump': flash })}
          title={tiebreak ? 'Tiebreak points' : 'Current game'}>
      {point}
    </span>
  )
}

function CompetitorRows({ e, a, b }) {
  const doubles = e.discipline !== 'singles'
  const lp = e.live_point ?? null
  const live = e.status === 'live'
  /* A postponed or carried-over match has a score even though nobody is
     playing: it is exactly the score play stopped at. It reads from the live
     snapshot like a live row — otherwise the row falls through to the
     completed scores, finds none, and shows an empty card for a match that
     is half played. Nobody is serving, though, so the ball stays off. */
  /* PLAY IS NOT HAPPENING. Postponed and to-be-completed say so on the row's
     own status; a SUSPENDED match says it inside its score payload instead,
     and was not counted here — so a match parked overnight kept the live row's
     dash in the point column, which reads as "we have lost the point" rather
     than "there is no point, nobody is playing". Both spellings, because a
     carry with no live point has only the first and a live suspension only the
     second. */
  const stopped = e.status === 'postponed' || e.status === 'to_be_completed'
    || e.live_scores?.[4] === 'suspended' || !!e.live_point?.suspended
  const hasLiveScore = live || stopped

  // Games: prefer the snapshot's own, exactly as the draw page does.
  const g = lp?.games ?? null
  const fromLive = hasLiveScore
    ? (g ? [g[0], g[1]] : (e.live_scores ? [e.live_scores[0], e.live_scores[1]] : null))
    : null
  /* The sets the row last had, whatever its status. A LIVE row reads its score
     from the live snapshot alone, so a single empty payload rendered no cells
     at all and the score vanished off the card until the next poll refilled it.
     The feed having nothing to say for one poll is not the score being nothing,
     and the completed sets on the row are still true. The blank is stopped at
     source now (see _has_sets in sofascore_doubles); this is the safety net, so
     a live row can never go blank again from a gap anywhere upstream. */
  const fromFinal = e.scores ? [e.scores[0], e.scores[1]] : null
  const sets = fromLive ?? fromFinal
  const n = sets ? Math.max(sets[0]?.length ?? 0, sets[1]?.length ?? 0) : 0

  /* HOW WIDE A SET CELL HAS TO BE, for THIS match.
     .sched-set holds 1.15rem so a super-tiebreak "10" cannot widen one line
     without widening the other — the two rows have to stay in column. But
     nearly every match on the sheet shows single digits, and the reservation
     was flat: four columns of a completed card held ~19px of two-digit room
     each for numbers about 8px wide, and the name — the only flexible thing in
     the row — paid all of it.
     So ask the score. Both lines are measured together and get the same
     answer, which is the property the alignment actually depends on; the
     tiebreak superscript counts too, since it lives in the gap and a
     two-digit one ("6" with a ¹⁰ beside it) needs the wider cell's slack to
     clear the next number even when the games are single digits. */
  const twoDigitCells = !!sets && sets.some(row => (row ?? []).some(c => {
    const { g, tb } = parseSet(c)
    return String(g ?? '').length > 1 || String(tb ?? '').length > 1
  }))

  // Who took each completed set, for the bolding. The set in play has no winner
  // and must stay unbolded — that is what makes "in progress" legible.
  const setWon = (i, side) => {
    if (!sets) return false
    // The last set present is normally the one being played, so it has no
    // winner yet. In a match tiebreak it is not — the tiebreak stands in for
    // the deciding set and is scored as a point, so every set in this list is
    // finished and the second one keeps the bold it earned.
    if (live && i === n - 1 && !lp?.match_tiebreak) return false
    const x = Number(parseSet(sets[0]?.[i]).g), y = Number(parseSet(sets[1]?.[i]).g)
    if (Number.isNaN(x) || Number.isNaN(y)) return false
    return side === 0 ? x > y : y > x
  }

  const endedWith = (side) => {
    const cells = (e.scores || [])[side] || []
    if (cells.some(c => /^w\/?o$/i.test(String(c ?? '').trim()))) return 'w/o'
    if (cells.some(c => /r$/i.test(String(c ?? '')))) return 'ret.'
    return null
  }

  /* WHO WON, in order of how much each source actually knows.

     1. The server says so. It reads the bracket match's winner (singles) or
        the row's own stamped winner_side (doubles, qualifying) — a recorded
        fact, not a reconstruction.
     2. The end marker. "w/o" marks the player who ADVANCED and "ret." the
        player who QUIT, so each names a winner outright — and both describe
        matches a scoreline cannot: a walkover has no sets at all.
     3. Only then, counting sets. This is the fallback of last resort because
        it is WRONG on the case tennis produces every week: a player who
        retires while ahead (6-4, 3-0 ret.) has more sets and lost the match.
        Reached only for an ordinary completed row whose winner the server
        has not stated, where it agrees with the record by construction. */
  const winnerSide = (() => {
    if (e.winner_side === 0 || e.winner_side === 1) return e.winner_side
    if (e.status !== 'completed') return null
    if (endedWith(0) === 'w/o') return 0
    if (endedWith(1) === 'w/o') return 1
    if (endedWith(0) === 'ret.') return 1
    if (endedWith(1) === 'ret.') return 0
    if (!e.scores) return null
    let x = 0, y = 0
    for (let i = 0; i < n; i++) { if (setWon(i, 0)) x++; if (setWon(i, 1)) y++ }
    return x === y ? null : (x > y ? 0 : 1)
  })()

  /* WHOSE SERVE IT IS WHEN THEY COME BACK. A suspended row already shows the
     ball; a match carried to another day is the same fact one night later —
     the player who was about to serve still is, and it is the first thing you
     want to know about a resumption. Shown on the abandoned day's row too, so
     the two halves of one match do not disagree. */
  const serving = (live || stopped)
    ? (lp?.serving ?? e.live_scores?.[2] ?? null) : null
  // The point stands too — it is where the game was when play stopped.
  const point = hasLiveScore && lp?.point ? lp.point : null

  /* How the match ENDED, when it did not end normally.
     parseSet strips the trailing "r" to read the games off a cell, so without
     this the schedule showed a retirement as an ordinary 4-1 win — a different
     match from the one that was played.

     Read off whichever side carries the marker, matching the bracket: a
     retirement marks the player who QUIT, a walkover marks the player who
     ADVANCED ("won by walkover"). The two sit on opposite sides on purpose;
     that is how they are stored. */

  const rows = [
    { players: a, side: 0, tbd: !!e.tbd_side?.includes('a') },
    { players: b, side: 1, tbd: !!e.tbd_side?.includes('b') },
  ]

  // Both teams together, so they are written the same way as each other, and
  // against the columns this row actually shows rather than a fixed guess.
  // Both lines of a match share one geometry, so one measurement serves both.
  const [nameBoxRef, nameBox] = useNameBox()
  /* ONLY A SIDE THAT USES THE ANSWER MAY CONSTRAIN IT.
     An unresolved side opts out of the ladder — it draws itself, at its own
     scale — so measuring it here charged the row for a line nobody renders:
     doublesLineOf joins the alternatives with " / " while the page shows
     "A or B", and every rung returns a printed alternative UNCHANGED (each
     arrives with no given name to give up), so no rung could ever fit and the
     ladder fell to its floor for the settled side beside it.
     Monterrey 2026-08-28 ESTADIO, the doubles semi-final: "M. Chwalinska /
     S. Kraus or S. Aoyama / E. Liang" took Joint/Xu down to a bare
     "JOINT / XU" on a phone — no flags, no given names — on a line with half
     the card free, while the LONGER "M. CHWALINSKA / S. KRAUS" had kept both
     the day before. It also broke the promise DOUBLES_RUNGS makes: the row
     ended up showing initials on one side and bare surnames on the other,
     which is the exact thing testing the sides together exists to prevent. */
  const dbl = doubles
    ? doublesPresentation(
        rows.filter(r => !isAltSide(r.players, r.tbd)).map(r => r.players),
        n, nameBox)
    : null

  return (
    <div className={clsx('sched-competitors', { 'sched-competitors--doubles': doubles })}
         style={twoDigitCells ? undefined : { '--sched-set-w': '0.85rem' }}>
      {rows.map(({ players, side, tbd }) => (
        <div key={side}
             className={clsx('sched-competitor', {
               'sched-competitor--won': winnerSide === side,
               'sched-competitor--lost': winnerSide != null && winnerSide !== side,
             })}>
          {/* The box the name actually has. Measured here, on the element that
              owns the width, and handed down — see useNameBox for why this
              cannot feed back on itself. */}
          <span className="sched-competitor-name" ref={side === 0 ? nameBoxRef : undefined}>
            <Side players={players} doubles={doubles} tbd={tbd}
                  tight={serving != null || point != null} sets={n}
                  form={dbl?.form} flags={dbl?.flags} box={nameBox} />
          </span>
          {/* A SLOT ON BOTH LINES OR ON NEITHER. The ball appears on one line
              only, so rendering it inline shifted that line's scores left of
              the other's and broke the column — hence a slot rather than a
              conditional element.
              But it is reserved per MATCH, not unconditionally: a finished or
              not-yet-started match can never show a ball on either line, and
              17px of a name box barely over 100px wide was being held for it
              on every completed card on the sheet. Keyed on (live || stopped),
              the same condition that decides whether `serving` is read at all,
              so a live row keeps the slot whether or not serve inference has
              landed yet and nothing pops in mid-match. */}
          {(live || stopped) && (
            <span className="sched-ball-slot">
              {serving === side + 1 && <ServeBall />}
            </span>
          )}
          {/* BEFORE the tick/cross, not between it and the scores.
              Everything here is fixed-width and right-packed, so an element's
              position depends on the total width of everything after it. With
              "ret." sitting after the mark, the row that had one pushed its
              cross left of the other row's tick — and the two stopped lining
              up. In front of the mark it is absorbed by the flexible name
              instead, and the marks stay in a column.
              Still ahead of the scores, where it qualifies them; after the
              numbers it read as another set. */}
          {endedWith(side) && (
            <span className={clsx('sched-end', { 'sched-end--wo': endedWith(side) === 'w/o' })}>
              {endedWith(side)}
            </span>
          )}
          {winnerSide != null && (
            <span className={clsx('sched-mark', winnerSide === side ? 'sched-mark--win' : 'sched-mark--loss')}>
              {winnerSide === side ? '\u2713' : '\u2717'}
            </span>
          )}
          <span className="sched-sets">
            {Array.from({ length: n }, (_, i) => (
              <SetCell key={i} cell={sets?.[side]?.[i]} bold={setWon(i, side)} />
            ))}
            {/* The point last, tinted apart from the games — it is a different
                kind of number and changes every few seconds. */}
            {point ? (
              <PointCell point={point[side] ?? '0'} tiebreak={lp.tiebreak} />
            ) : live && !stopped && (
              /* SAY "NO POINT RIGHT NOW", DON'T SILENTLY DROP THE COLUMN.
                 A live row with no fresh point used to render nothing, so
                 the whole score column shifted and it read as the match
                 losing its scores. A dim dash holds the place and the
                 tooltip says why. */
              <span className="sched-point sched-point--stale"
                    title="Live point unavailable right now — set scores are current">
                –
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  )
}

export default CompetitorRows
export { PlayerName, Side, ServeBall, SetCell, PointCell }
