# Flashscore as a draw-shape source — evaluation

Investigated 2026-09-21. No application code was changed. **No request was made to
any Flashscore- or Livesport-owned host** at any point, by me or by any subagent;
the Livesport terms quoted below come from a search index, not a fetch. No
Sofascore request was made, and no proxy was used, probed or considered.

## BOTTOM LINE

**Don't adopt Flashscore.** But the investigation found a real bug underneath the
symptom, and a free official source that is better than anything for sale.

*Flashscore has the data, and the only route to it is the one route we may not use.*
This is the sharpest finding of the investigation, and it cuts against the
comfortable answer. Flashscore's own per-tournament draw feed
(`dr_<tournamentId>_<stageId>`) **does** carry what we need: the `HI`/`AI` fields
fuse seed and entry type into one parenthesised string, verified against a real
128-player ATP draw payload captured in a public GitHub fixture — seeds `(1)`–`(32)`,
`(Q)`, `(WC)`, `(LL)` all present, with `(RET.)` overloaded into the same field.
`PA` lists 128 entrants in bracket order, so its index gives bracket position
(*inference from one sample; no repo states it as a contract*), and a bye is
reportedly a blank-named `PA` slot (*documented by one author, unverified — the
sample is a Slam draw, which has no byes*).

But **every managed route that would absorb the egress risk fails to expose those
fields.** `seed`, `qualifier`, `wild`, `lucky` and `bye` appear nowhere in RapidAPI
FlashScore's OpenAPI spec — its draw endpoint documents *zero* response fields;
FlashLive Sports has no draw endpoint at all; parse.bot's FlashScore listing has no
tennis draw; and of 62 Apify Flashscore actors, all closed-source, the only one
claiming byes is a six-day-old build with two users, one run in 30 days, and no
schema. So the choice is: pay a wrapper that cannot give us the fields, or read the
feed ourselves — which is precisely the Akamai-fronted direct access the owner
forbade, and for good reason. **There is no third door.** The one adverse timing
fact also stands: Flashscore's tennis *day* feed is a rolling **−7…+1 days**, so a
draw released two days out is not in it (the `dr_` feed is not day-bounded, but
reaching it means hitting Flashscore).

Meanwhile 55 of our 111 2026 draws (every 28, 30, 48, 56 and 96) need byes
expressed correctly — including these two, which are 28-draws with four byes each.

*One paid API — not Flashscore — actually could, and it is still the wrong buy.*
`api-tennis.com`'s `get_draw` is the only route surveyed that documents slot
linkage (`draw_key`, `next_slot_key`) **and** byes (`status: "BYE"`,
`second_player: null`) alongside seeds and entry markers, and it states its
pre-publication behaviour explicitly via a `source` field. It costs **$40/mo
minimum** with no free tier, omits nationality from the draw payload, and — the
part that would actually hurt us — returns **abbreviated names** (`"D. Medvedev"`).
Our entire identity pipeline resolves on full names (`te_slug`, `sofa_player_id`,
`name_keys`), and `_resolve_against_field`'s own docstring notes that
`surname+initial` matching is safe *only inside a closed candidate set* — which is
precisely what we would not have when bootstrapping a draw from nothing. Paying
$480/year to import a name-matching problem, for shape the tour publishes free, is
not a trade worth making.

*The actual bug is ours, and it is a namespace.* The Chengdu and Hangzhou draws are
on Wikipedia **right now**, complete, in the `Draft:` namespace — verified
first-hand: `Draft:2026 Chengdu Open – Singles` (page 84283819) is 11,499 bytes with
`| draw = 28 (4 Q / 3 WC)`, 40 named `RD1-teamNN` slots, 24 filled `RD2` slots and
seed cells carrying `1`–`8`, `Q`, `WC`, `NG`, in the same
`{{16TeamBracket-Compact-Tennis3-Byes}}` template our parser already handles.
One editor began staging in `Draft:` around **2026-07-28** and has done so since;
before that he created in mainspace directly. **After the move the `Draft:` title
survives as a redirect** — verified: `Draft:2026 SP Open – Singles` → `2026 SP Open
– Singles` — and our fetcher already sets `redirects=1` (`scraper.py:409`). So a
`Draft:`-prefix retry reads the draft before the move and the real article after it,
through the same code path and the same parser. There is a **second live instance
right now**: `Draft:2026 China Open – Women's singles` (page 84253789) has existed
since 2026-09-17 with mainspace still missing (our draw 147, 96-draw, zero entries).

*And the durable fix costs nothing.* The official ATP main-draw sheet is live and
free at a path we already fetch from:
`protennislive.com/posting/2026/7581/mds.pdf` returned **HTTP 200, 115,787 bytes,
`Last-Modified: Mon, 21 Sep 2026 09:06:34 GMT`** — published and revised today, two
days before play. It carries all seven required fields: slot number 1..32, the
literal `Bye` at slots 2, 10, 23 and 31 (which **cross-validates exactly** against
Wikipedia's absent-RD1-slot encoding), seed in its own column, IOC nationality,
`Qualifier` placeholders and the full entry-code set. `tournaments.atp_tournament_id`
is already populated for **58 of 58** men's 2026 draws. It is a PDF, and
`oop_parser.py` already reads seeds and entry designations off this host's printed
sheets.

*And one field we may already be throwing away.* A third-party project that builds slam brackets reports that **Sofascore's `cuptrees` carries `teamSeed`** — `"1"`…`"32"`, or `"Q"`/`"WC"`/`"LL"` — on the very payload `_field_of` already fetches, and `_main_draw_teams` discards everything but `id`, `name`, `country` and `type`. If that holds, seed and entry type are reachable for every resolved draw at **zero additional requests**. Unverified here (confirming it costs one request) and it would still not give byes, but it is the cheapest unexplored lead in the whole survey — see §5.5.

**Recommendation: three cheap Wikipedia-side fixes now (§5.1–5.3), the official ATP
sheet as the durable authority when there is appetite (§5.4), and no vendor.**

## 1. The prompting failure, measured

`draws` 122 (Hangzhou) and 145 (Chengdu) in `backend/tennis_fantasy.db`:
`draw_size 28`, `num_rounds 5`, start `2026-09-23`, `wiki_page_id NULL`, **0**
`draw_entries`, no `sofa_tournament_id`. The brief's description is exact.

2026 draws whose release was observed live (`da_days_before` 0–10):

| Tier | draws observed | lead, days before start |
|---|---|---|
| ATP/WTA 250 | 21 | 1–2 |
| ATP/WTA 500 | 10 | 1–2 |
| ATP/WTA 1000 | 4 | 2–3 |
| Grand Slam | 4 | 3–4 |
| **total** | **39** | **1–4, never later** |

`bracket_first_seen_days_before` agrees (1–4 days) for every draw except four all
stamped `2026-07-27` — one shared date, which is when the column started being
measured. *Inference, but a safe one: four unrelated events on three continents do
not publish their draws on the morning of play.*

Hangzhou and Chengdu are at start-minus-2 today. Six of the sixteen draws with a
`bracket_first_seen` observation first appeared at exactly minus-2 and two at
minus-1, so **these two are inside the normal window, not past it**. This codebase's
own definition of late agrees: `release_deadline(2026-09-23, 2026-09-19)` is
**2026-09-22**, so `_check_draw_health` Check 2 is deliberately still silent. Their
`draw_release_direct` of 2026-09-19 (a four-day lead) is earlier than any ATP 250
has actually released in our record; the estimate being ~2 days optimistic is a
secondary defect on display.

The held email is also correct behaviour, not a symptom. `(2026, 38)` is in
`scheduler.TOUR_SPLIT_WEEKS`, so `release_bucket` splits week 38 by gender: the WTA
half (Singapore 144, Korea 146) was notified 2026-09-19, and the ATP half is a
separate bucket correctly waiting for both of its members. Nothing is stuck.

### Historical timing, and an important caveat against my own figures

First revisions of the previous editions of these two events, all `create` actions
(not moves), born at 10–11.5 KB — which *is* a filled 28-draw:

| Article | First revision (UTC) | Start | Lead |
|---|---|---|---|
| 2024 Hangzhou Open – Singles | 2024-09-16T09:12Z | 2024-09-18 | −2 d |
| 2024 Chengdu Open – Singles | 2024-09-16T09:35Z | 2024-09-18 | −2 d |
| 2025 Hangzhou Open – Singles | 2025-09-15T09:04Z | 2025-09-17 | −2 d |
| 2025 Chengdu Open – Singles | 2025-09-15T10:34Z | 2025-09-17 | −2 d |

Across 61 articles in `Category:2025 ATP Tour singles`, Δ(first revision − start)
is modally **−2 days (25 events)** then **−3 (11)** — 36 of 61 at −2/−3, with every
positive Δ an artifact (Masters 1000 `date=` misparse; combined events whose main
article carries the WTA week; one `– final` sub-article). **Zero confirmed cases of
an ATP singles draw article landing after play began.**

**Caveat that cuts against that histogram, and it matters:** a page move carries its
history, so for a moved page the mainspace "first revision" timestamp *is* the
Draft creation time. The −2/−3 distribution is therefore sound for 2025 (no Draft
habit existed) but **understates lateness for 2026 events after late July.** The
measured Draft-only windows show the blind spot is sometimes days, not hours:

| Event | Drafted | Moved | Draft-only window |
|---|---|---|---|
| 2026 SP Open – Singles | 02:43:45Z | 02:44:04Z | 19 s |
| 2026 National Bank Open – Men's singles | 22:50:21Z | 22:52:42Z | 2.4 min |
| 2026 Singapore Tennis Open – Singles | 2026-09-18T02:22Z | 2026-09-18T12:36Z | 10.2 h |
| 2026 US Open – Men's singles | 2026-08-18T23:40Z | 2026-08-23T22:21Z | **~5 d** |
| 2026 US Open – Men's singles qualifying | 2026-08-05T11:42Z | 2026-08-18T23:17Z | **~13.5 d** |
| 2026 China Open – Women's singles | 2026-09-17T10:50Z | **still missing** | **>4 d, ongoing** |
| 2026 Chengdu / Hangzhou – Singles | 2026-09-20T22:50Z / 22:58Z | **still missing** | **>11 h, ongoing** |

So the honest framing is: **Wikipedia is not late; our read of it has a blind spot
that opened in late July and can last days.** That is a bug to fix, not a source to
replace — and fixing it is a title prefix.

## 2. Field coverage

"We consume" means this codebase reads it today.

| Field | Wikipedia (`services/scraper.py`) | Sofascore (`services/sofascore.py`) | Flashscore — *via wrapper* / *raw `dr_` feed* |
|---|---|---|---|
| name | Yes — `PlayerEntry.name` | Yes — `team.name`, stored as `DrawEntry.sofa_name`, preferred for display | Yes — `PARTICIPANT_NAME` (`flashlive-sports`); `flashscore4`'s draw response is undocumented, but names are the one certainty |
| nationality | Yes — `PlayerEntry.nationality`, 3-letter | Yes — `team.country.alpha3`, used only to veto a fuzzy name match (`_countries_conflict`) | Yes on `flashlive-sports` (`COUNTRY_ID`, `COUNTRY_NAME`) — but that wrapper has no draw at all. On `flashscore4`'s draw: **could not confirm** |
| **bracket_position** | **Yes** — 1-indexed slot from the template's `RD1-teamNN` keys; `MatchResult.player1_position/player2_position` rebuild the tree | **No** — `_main_draw_teams` flattens the cuptree to a *set* of teams keyed by id; nothing positional is read or stored | *Wrapper:* **no** — no wrapper documents a slot index. *Raw feed:* **probably yes** — `HP`/`AP` index into `PA`, which runs 0→127 in bracket order in the verified fixture. **Inference from one sample**, stated as a contract by nobody |
| seed | **Yes** — `_parse_seed`, incl. compounds like `20/WC` and `Q/LL` | **Not consumed** — `grep seed backend/app/services/sofascore*.py` returns nothing, and `_main_draw_teams` keeps only `id`/`name`/`country`/`type`. But a third-party bracket project reports the cuptree carries **`teamSeed`** (`"1"`…`"32"`, `"Q"`, `"WC"`, `"LL"`) — i.e. seed **and** entry type may already be in a payload we fetch. Unverified; one request settles it (§6) | *Wrapper:* **no** — `seed` appears nowhere in either RapidAPI FlashScore wrapper's docs or OpenAPI spec. *Raw feed:* **yes, verified** — `HI`/`AI` carry `(1)`–`(32)` in a captured 128-draw fixture |
| **entry_type** (Q/WC/LL/PR/SE/Alt/NG) | **Yes** — `ENTRY_TYPES`, seven values, canonicalised | **Not consumed**; possibly present as `teamSeed`, which multiplexes entry type with seed (see the seed row) — so the "Sofascore has no entry type" claim is now doubtful, not settled | *Wrapper:* **no** — `qualifier`/`wild`/`lucky` appear nowhere in either RapidAPI FlashScore spec; one Apify actor documents `entry_status` with the value set never enumerated. *Raw feed:* **yes, verified** — `HI`/`AI` carry `(Q)`, `(WC)`, `(LL)` (no `ALT` in the sample), fused with the seed. **So this was a gap in the MOCK, not the source** |
| **first-round bye** | **Yes** — two independent signals: a lone R1 occupant, and a seed placed directly in RD2 with both RD1 slots empty (`bye_positions`); `MatchResult.is_bye` | **No** — a bye is not an event, so it cannot appear in an event-derived tree | *Wrapper:* **no** — `bye` appears in neither RapidAPI FlashScore spec except as a *cricket* statistic enum; one Apify actor's one-line prose claims it with no field name. *Raw feed:* **could not confirm** — reportedly a blank-named `PA` slot, but the only published fixture is a Slam draw with no byes |
| draw_size | **Yes** — from the bracket template variant, incl. the `-Byes` suffix that decides whether byes are legal at all. Also stated as `draw=28S` in the main article, 26 days early | Partially — `numberOfSets` is stated; size is not read | **Could not confirm** |

For reference: the official ATP sheet (§5.4) carries **all seven**, verified today
and free. `api-tennis.com` (§3, $40/mo) documents all seven **except nationality**,
and abbreviates names. No other evaluated source carries bracket position and byes
at all.

### Are entry_type and byes gaps in the mock, or in the source?

**Short answer: entry type is a gap in the mock; byes are unconfirmed everywhere
that derives a bracket from matches.** The reasoning, including where my first
reading was wrong:

1. Flashscore is a live-scores product and its bracket is assembled from match
   objects — which is what the mock's `next_match_id` is, a child-match pointer. A
   public consumer of `flashscore4`'s draw endpoint
   (`github.com/sromeroubisos/Grupo-22-Scores`) passes the draw payload through the
   same generic parser it uses for fixtures, reading it as a **flat match list**
   with no positional tree; across that 85 KB integration there is no reference to
   seed, bye, qualifier, wildcard or bracket position. Its own tennis pages use
   ESPN instead, and its ESPN model *does* carry a per-side `seed`. Suggestive, not
   proof.
2. A first-round bye is not a match, so there is no object to hang it on. The only
   way a match-graph bracket can express one is a round-1 match with one empty side
   — indistinguishable from a round-1 match whose second name is unpublished.
   `scraper.py` records that exact conflation as a past bug here: reading lone
   occupants as byes "invented 27 free byes" and advanced two players who had not
   played.
3. **On entry type I was wrong, and the mock is the thing at fault.** My first
   reading was that a scores product has no reason to carry an acceptance-list
   fact. The captured `dr_` fixture disproves it: `(Q)`, `(WC)` and `(LL)` are
   right there in `HI`/`AI`. So **entry type is a gap in the owner's mock, not in
   Flashscore** — and by the same token Sofascore's reported `teamSeed` (§5.5)
   suggests I was wrong about that source too. What survives of the argument is
   narrower and still decisive: **byes** remain unconfirmed in any match-derived
   feed, and byes are the field a match graph genuinely cannot hold. Recorded as a
   correction rather than quietly edited, because the original inference was
   plausible and wrong, and the next person deserves to know which half held up.
4. **The paid market mostly corroborates it, with one exception that proves the
   point.** Matchstat — the best-documented *live-scores-derived* draw, with a
   36 KB worked sample — has **no slot index and no bye field**. Sportradar has
   `qualification_path`, `country_code` and `seed` as separate fields, and **no bye
   and no `draw_size`**. The exception is `api-tennis.com`, which has slot linkage
   and an explicit `BYE` status — and it is the exception *because* it consumes an
   official draw feed rather than deriving a bracket from matches: its own `source`
   field distinguishes `"draw_feed"` from `"reconstructed_from_results"`, and only
   the former carries the shape. That is the whole thesis in one field name. A draw
   sheet is a positional artefact; a match graph is not, and reconstructing one
   from the other is exactly what loses the byes.

Wikipedia's bye encoding in these very drafts is an **absent RD1 slot id** — both
events omit top-half slots {1,2,9,10} and bottom-half {7,8,15,16}, with seeds 1–4
placed at `RD2-teamNN`. The official PDF prints 32 slots with the literal `Bye` at
2, 10, 23, 31 (23−16=7, 31−16=15). **The two sources agree exactly.** That
agreement is what a real draw-shape source looks like.

## 3. Access routes

From provider documentation and the OpenAPI specs embedded in served marketplace
HTML. No Flashscore/Livesport host was contacted.

### The Flashscore routes

| Route | Health | Draw endpoint | Price |
|---|---|---|---|
| [RapidAPI `flashscore4`](https://rapidapi.com/rapidapi-org1-rapidapi-org-default/api/flashscore4) — RapidAPI's own first-party org | ACTIVE; created 2025-07-02, updated 2026-08-14; popularity 9.9, latency 310 ms, success 100%; 44 endpoints | **Yes** — `GET /api/flashscore/v2/tournaments/draw` (`tournament_id`, `tournament_stage_id`, from `/tournaments/ids`), "Returns draw bracket for a specific tournament stage" | Free **500/month** · PRO $3/mo **1,000/day** · ULTRA $9/mo 10,000/day · MEGA $19/mo 35,000/day |
| [RapidAPI `flashlive-sports`](https://rapidapi.com/tipsters/api/flashlive-sports) — Tipsters CO | ACTIVE; created 2022-07-08, updated 2026-06-25; **success 75%**; 70 endpoints | **No.** A firm negative, not thin docs: the full 70-route list *and* the provider's own complete reference contain no bracket/cuptree route. Closest is `/v1/tournaments/fixtures` — flat, paginated, no tree, no slot, no seeds | Free 500/mo · $15/mo 10,000/mo · $55/mo 75,000/mo · $99/mo unlimited |
| RapidAPI `tipsters/flashscore` | **DEAD** — 404 shell, no API object, no plans; only `/discussions` still indexed | n/a | n/a |
| Apify — 62 Flashscore actors, 37 mentioning tennis | Churning marketplace; nearly all single-author, 1–5 users, built in the last four months | Only **one** claims a draw: `zen-studio/flashscore-tennis-api`, **2 users**, build 2026-09-15 | `/draw` free tier |
| parse.bot FlashScore API | Updated 2026-09-20; "2/2 endpoints passing" — **of 19 endpoints** | **No** tennis draw, bracket, seed or bye | Free 200 credits/mo · Developer **$100/mo** |

**The decisive gap: `flashscore4` registers a draw endpoint and documents no
response for it.** It is absent from the listing's embedded OpenAPI spec entirely;
its sibling `/matches/draw` is present and its whole documented response is
`"200": {"description": "Match draw information"}`. A case-insensitive sweep of the
served page (which *does* carry the full spec) returns **zero** hits for `seed`,
`qualifier`, `wild`, `lucky`, `bye`, `cuptree`.

`zen-studio`'s actor is the only product claiming what we need — `/draw` described
verbatim as "The bracket: rounds, entrants, and who received a bye", with per-player
`seed` and `entry_status`. **But: no response schema, no sample, no field list, the
`entry_status` value set never enumerated, no slot index, two users, six days old.**
That is the thinnest possible evidence for the most important question, on the least
proven dependency here. The adopted Flashscore tennis actors are explicitly
fixtures-only: `extractify-labs/flashscore-tennis-matches` (2,032 users, 13,411
successful / 0 failed runs in 30 d, $1.00/1,000 results) documents 24 fields, has no
draw, and carries `ranking` but **not** seed. Beware SEO padding —
`edwin_beale/flashscore-tennis-scraper`'s title says "draws" and its README
documents none.

**Timing — the one hard fact, and it is adverse.** Two independent actor READMEs
state Flashscore's tennis feed is a rolling nine-day window: "7 days of results
back, today, and tomorrow's fixtures" and "a rolling 9 day window: 7 days back
through 1 day ahead", with `dayOffsets` capped at −7…+1. **A draw released two days
before play is not in that feed.** The tournament `/bracket/` page is a separate
feed — Flashscore does ship a bracket UI, evidenced by indexed
`/tennis/atp-singles/{slug}/bracket/` URLs and `standings_draw.*.css` build assets —
and **whether it is populated at draw release could not be confirmed from any
documentation, blog post, forum post or GitHub issue on any non-Flashscore host.**
The slug carries no year; *inference:* the page reflects the current edition, which
is why a Flashscore route would need a season-by-season slug map (§4.1).

### The raw feed — where the data actually lives, and why that settles it

The fields the wrappers lack are in Flashscore's own protocol. Verified by a
subagent against `omkarcloud/flashscore-scraper`'s captured fixture
(`flashscore/fixtures/draw.txt`, 38,064 bytes, a real 128-player ATP draw) pulled
from raw.githubusercontent.com — **no Flashscore host was contacted to establish
this**:

- Feed shape `dr_<tournamentId>_<stageId>`, records `~`-separated, fields `¬`,
  key/value `÷`, single `x-fsign` auth header.
- **`HI`/`AI` fuse seed and entry type**: observed values include `(1)`–`(32)`,
  `(Q)`×8, `(WC)`, `(LL)`, and `(RET.)` — including the combined `"(RET.) (28)"`,
  which a naive parser reads as a seed. Emitted only when there is something to
  print, so direct acceptances have no key. Seeds persist across rounds.
- **`PA`** lists 128 entrants as `idx_Name` in bracket order, `HP`/`AP` index into
  it — so the `PA` index is effectively the slot. *Inference from one sample; no
  repo states it as a contract.*
- **Bye** is reportedly a `PA` slot with a blank name (`campaneros/NN_tennis`
  handles it explicitly). **Unverified** — the fixture is a Slam draw, which
  correctly has zero blank `PA` names, and no published fixture covers a 28-draw.

Two half-complete reference parsers exist (`omkarcloud/flashscore-scraper` reads
`HI`/`AI` but mis-groups `RI`; `campaneros/NN_tennis` handles byes and `RI` but
ignores `HI`/`AI`), and the fixture means a parser could be written and tested
offline. The wider open-source picture is otherwise barren: PyPI 404s on every
plausible package name, `soccerdata` (2,081★) and `ScraperFC` (412★) have **no**
Flashscore reader, and GitHub `flashscore tennis` returns 11 repos with a maximum
of **2 stars**. Notably `tsenoner/TennisArc` evaluated Flashscore for draws and
**rejected it** — "no API, obfuscated, scraping-only" — taking draws from
Sofascore's `cuptrees` and the official Grand Slam IBM JSON feeds instead.

**Why this closes the question rather than opening it.** The route with the fields
requires direct access to an Akamai-fronted host from an egress IP that production
shares with Sofascore — the exact risk the brief forbids, and the reason the managed
wrappers were being evaluated in the first place. The wrappers exist to launder that
risk and **none of them exposes `HI`/`AI`**. Note also that no surveyed repo
mentions Akamai at all and several report no rate limiting from direct egress —
which is a **negative finding, not reassurance**: these are recent, low-volume
readers, none fetching at production scale, so the owner's caution is unaddressed
rather than contradicted.

### Non-Flashscore paid tennis draws, for completeness

The brief asked whether another source is a better answer. These are the real
contenders, and each fails on a different required field:

| Vendor | Has | Missing | Price |
|---|---|---|---|
| **Matchstat "Tennis API - ATP WTA ITF"** (RapidAPI, updated 2026-09-19, success 99%, 171 routes) — `GET /tennis/v2/tournament/{atp\|wta}/{tournament}/{year}/draws`, the **only** listing with a field-level documented draw (36 KB worked sample) | `player1.name`; `countryAcr` 3-letter IOC; `seed1`/`seed2` **and** entry markers — the seed field multiplexes them (`"1"`, `"q"`, `"WC"`, `"ALT"` all observed); `roundId`; `best_of`; `h2h` | **No slot index** — the `draw` integer is a sub-draw/section number, not a position (it is 1 on every singles row; two qualifying rows share `roundId 1` with `draw` 1 and 2). **No bye**: zero occurrences of `bye`, `walkover` or `w/o` on the listing or in Matchstat's own docs. `LL`/`PR` not observed. `winner_entry`/`loser_entry` exist in the schema but are null in all nine sample rows. Undocumented round codes 9 and 10 appear in the samples. Its Fixtures Response-Properties table omits `seed1`/`seed2` entirely (they appear only in the sample), and `potential-fixtures` promises "round and draw position" while returning neither — so it is **not** a pre-publication draw substitute | Free **50/day** · PRO $29/mo 150k/mo · ULTRA $59/mo 1.2M/mo · MEGA $99/mo — **plus a plan-independent 100 req/min per-IP ceiling** documented in Getting Started, which matters for any backfill. Staleness signal: its own marketing site `tennis-api.com` quotes different prices ($10/mo 10k, $39/mo 75k) than the live RapidAPI billing plans; the RapidAPI objects are what bills |
| **api-tennis.com** — `GET /tennis/?method=get_draw&tournament_key=…&tournament_season=…&include_qualification=1` (own docs, not RapidAPI; © 2026, actively developed). **The only route that documents every field we need** | `brackets[].stage`, `qualification` (bool), **`draw_size`**; `rounds[].round_name`; per match `draw_key` (401, 402…) — a stable per-slot id, `match_number`, **`next_slot_key`** (401 and 402 both → 433), i.e. an explicit parent-pointer topology walkable without inferring from who-played-whom; **`"status": "BYE"` with `second_player: null` and `match_key: null`**, the seeded player in `first_player` and a `next_slot_key` — exactly our representation; per entrant `player_key`, `name`, `seed` (`"1"`, and `"WC"`/`"Q"` shown by example); **`source`: `"draw_feed"` vs `"reconstructed_from_results"`**, with unplayed rounds carried as slots whose status is `TBA` (the prose calls them "TBD") and which fill in as each round is played — i.e. the pre-publication question is *answered in the docs* | **No nationality** in the draw entrant object at all (`player_key`, `name`, `seed`, `logo`) — needs a `get_players` join on `player_key`. **Names abbreviated** `"D. Medvedev"` — see the bottom line for why that is the real cost here. **Seed and entry type share one string**, so a seeded wildcard is inexpressible. `LL`/`ALT`/`PR` tokens not shown in the sample: could not confirm. Draw source never named ("our data provider") — do **not** assert it is or isn't Flashscore-derived. Data-quality smell in their own sample: `"tournament_country": "Atp Singles"` | Starter **$40/mo** 8k req/day · Premium $60 80k/day · Business $80 200k/day · Ultra $120 2M/day. Draw on all tiers. 14-day trial, **no permanent free tier**. No published per-second limit |
| **Sportradar Tennis v3** — `/seasons/{id}/info` | `seed` (int) **and** `qualification_path` as separate fields — all five values confirmed verbatim (`seeded`, `qualified`, `wildcard`, `luckyloser`, `alternative`) — plus inline `country_code`; `bracket_number`. ATP 250 is Tier 2 "Official data" | **No bye field anywhere** (grepped across bracket-building, schedules, coverage tiers, update frequencies, monitoring, scenarios, api-basics: zero hits). **No `draw_size`** — docs say "Do not assume draw sizes". Bracket wiring is a second call carrying no competitors or seeds | Quote-based enterprise, **not published** |
| RapidAPI "TennisApi" (REcodeX) — `/cup-trees`, `operationId getTournamentDrawBracket` | A bracket route exists | **Every** response typed as `JSONResult: additionalProperties: true, "Generic JSON proxy payload"` — no field names, no example. Entrant fields undiscoverable from docs | Free 50/day · $9.99/mo → $24.99/mo |
| Goalserve / BetsAPI / Entity Sport / API-Sports | — | **No tennis draw endpoint at all.** Goalserve's tennis XML has zero occurrences of `draw`, `bracket`, `seed`, `bye` or `round`, and `documentation.goalserve.com/v1/` is the InPlay betting module only. BetsAPI's only `bracket` mention is a football-framed `league/table` changelog line. Entity Sport has tennis but no draw. **API-Sports has no tennis product at all** — `api-sports.io` 403s (Cloudflare), so this was triangulated from first-party evidence: Wayback CDX over the whole domain shows archived `/documentation/` snapshots back to 2020–21 for every other sport and **zero snapshots ever** for `/documentation/tennis/v1`; their 2026-08-26 homepage snapshot lists thirteen sports and no tennis; `rapidapi.com/api-sports/api/tennis` returns "API not found"; and their RapidAPI org page has zero occurrences of "tennis" across 218 KB. The rubric is N/A there because there is no product, not because docs were thin; the brief's "Tennis API by API-Sports" is a conflation with the separate company api-tennis.com | $150–$900/mo |
| **Free open data** | — | Sackmann's `tennis_atp`/`tennis_wta` repos are **gone** (only `tennis_MatchChartingProject` remains), and were always completed-matches-only. Tennis Abstract's Chengdu/Hangzhou pages are empty shells today; its populated pages have seeds but no slot order, entry types or byes. Wikidata carries `P1132` (number of participants = draw_size) **post hoc** and no bracket. Every PyPI/GitHub "tennis draw" package is either 404 or a scraper *of* the official PDF | free |

**Ranked, if a purchase is ever forced:** (1) `api-tennis.com` `get_draw` — the only
route documenting seeds, entry markers, slot linkage *and* byes, and the only one
that states its pre-publication behaviour; $40/mo, no free tier, no nationality,
abbreviated names. (2) Matchstat — seeds + entry markers + inline `countryAcr`
confirmed by sample, no slot index, no bye; from $29/mo with a free 50/day tier.
(3) `flashscore4` — a draw endpoint exists and is cheapest ($3/mo, free 500/mo) but
documents zero response fields. (4) FlashLive Sports — no draw endpoint at all.
**None of these is a reason to spend money while §5.1–5.4 are unbuilt and free.**

**Dead/abandoned, flagged so nobody builds on them:** RapidAPI "Ultimate Tennis"
(success rate **0%**, updated 2025-04-29), "Tennis Live Data" (listing no longer
exists; search engines still show cached titles), and `tipsters/flashscore` above.
Also: a search result appeared to credit "Ultimate Tennis" with a draw endpoint
using language that is **verbatim api-tennis.com's own description** — a search
engine conflation, not evidence.

### Licensing

Livesport s.r.o.'s Flashscore terms state that without prior written authorization
visitors are not authorized to copy, distribute, transmit, display, reproduce or
otherwise use the content of the website. *(Search-index snippet of
`livesport.eu/terms/flashscore_com/`; not fetched — Livesport owns Flashscore and
the no-contact constraint covers its hosts.)* Routing through a scraper does not
change the term; it changes who breaches it first.

Apify pushes that risk onto the customer. General T&C (effective 2026-07-09): §5.8
"You are solely responsible for the legality … of all Customer Data"; §6.2 process
"only the Customer Data that you are authorized to access"; §11.1 "Should you use
the Services or Actors to extract Customer Data from unauthorized sources, you shall
be responsible for compensating any damages … and/or any claims of the affected
third parties", plus a full indemnity — against a §12.1 liability cap of **$1,000**.
No clause grants a right to redistribute output. Their own COO, on their legal blog:
"An ethical scraper does not re-publish or sell original works for its own profit.
That's piracy, not scraping", citing EU Directive 96/9/EC database rights, under
which "even facts can be protected if their collection … required substantial
investment."

**This repository is public and the site is public.** A term-violating,
self-indemnified dependency on a six-day-old actor is not a trade worth making for
draw shape available free from the tour itself.

## 4. What would break or need building here

1. **Tournament identity, and our existing resolver cannot help.**
   `_resolve_against_field` scores a candidate Sofascore tournament against *our
   own* `draw_entries`, and these draws have zero — so it structurally cannot
   bootstrap the case in question. Its one escape hatch (the `unpublished` branch)
   fires only when exactly one name-and-category candidate survives, and its own
   comment concedes it is the only place a tournament is accepted without checking
   its field. Moot here anyway: Sofascore has the tournaments (23614, 9402) and
   2026 seasons (82387, 82383) but `cuptrees` and `events/next/0` both 404, so
   **Sofascore is behind Wikipedia, not ahead.** A Flashscore route would have to
   solve identity from nothing — no Flashscore id exists anywhere in our schema,
   and a year-less slug means a hand-maintained map for ~98 tournaments a season,
   refreshed as events are renamed and relocated. (Matchstat keys on the tournament
   *name*, which is the same problem wearing a different hat: `_search_terms` and
   the "Adelaide" / "Adelaide 2" / two-live-Estoril-ids cases in
   `_resolve_against_field`'s docstring are exactly why name keys are unsafe here.)
   Note the contrast: **ATP identity is already solved** —
   `tournaments.atp_tournament_id` covers 58/58 men's 2026 draws, Chengdu 7581 and
   Hangzhou 4713 included.
2. **A second ingest implementation, or a `ParsedDraw` adapter.** Everything
   downstream of `scrape_tournament` is written against `ParsedDraw`
   (`scraper.py:87`): `players: list[PlayerEntry]` with
   `bracket_position/name/nationality/seed/entry_type`, and `matches:
   list[MatchResult]` with `player1_position/player2_position/winner_position/
   is_bye`. The ~200 lines of `_do_scrape` (`routers/tournaments.py:1845`) that
   stamp `draw_size`, `num_rounds`, city, country, `bracket_first_seen_at`,
   `draw_released_direct_at`, `da_days_before` and `closing_time` all key off that
   object. The seam is real and usable — but a source without `bracket_position`
   and `is_bye` does not fill those fields with less detail, it fills them with
   wrong data: a 28-draw arrives as a 32-slot bracket with four phantom R1 matches.
3. **Release detection is defined in Wikipedia's terms.**
   `draw_substantially_complete` (≥50% of non-Q/LL slots) and `bracket_published`
   (≥`BRACKET_PUBLISHED_MIN_UNSEEDED` = 4 named **unseeded** players) are
   heuristics for "an editor has finished transcribing". A feed is complete or
   absent, so it needs a different rule — and if two sources can stamp
   `bracket_first_seen_at`, next season's estimate starts learning from a mixture
   of "when the tour published" and "when an editor typed it up", the exact
   conflation that field's comment exists to prevent.
4. **Wikipedia must stay the record of shape, so any second source needs the
   `uso_draw.py` discipline**: fill only an empty side of a round-1 match, never
   overwrite a filled slot, never touch results, and **reuse the existing unnamed-Q
   row's id** rather than recreating it — picks point at `draw_entries.id`, and
   getting this wrong already cost 11 slots and 30 orphaned picks at the 2026 US
   Open. Note what `uso_draw.py` cannot do: it reads existing round-1 `Match` rows,
   so it *supplements* a bracket Wikipedia has already built. It could not have
   bootstrapped Hangzhou either.
5. **Operational risk imported.** A scraper wrapper breaks when the target's markup
   or internal feed changes, on the target's schedule, with no notice and no
   contract. Our Wikipedia parser is pinned to templates stable for years. A dead
   wrapper is a worse dependency than a late Wikipedia page — and two of the six
   Flashscore routes surveyed are already dead or decaying.

## 5. What to do instead

### 5.1 `Draft:` fallback — fixes today's outage

When mainspace `{YEAR} {Event} – Singles` is missing, retry the identical title with
a `Draft:` prefix. Same fetcher, same parser, and because `scraper.py:409` already
sets `redirects=1`, the same call transparently follows to mainspace once the page
is moved — **verified first-hand**: `Draft:2026 SP Open – Singles` resolves to
`2026 SP Open – Singles`. Candidate titles are built in `discovery.py:384-410`.
`EventStreamListener` matches on `event["title"]` with no namespace filter
(`eventstream.py:187-207`) and the recentchange stream's title is
namespace-prefixed, so adding the `Draft:`-prefixed title to the subscription set
needs no matcher change.

**Trap:** `wiki_page_id` is `unique=True` (`models/tournament.py:219`) and gets
pinned at `scraper.py:1228`. A Draft page has a different page id and is later
redirected or abandoned. **Read Draft by title only; never persist a page_id
resolved from a `Draft:` read.**

**Caveat:** this is one editor's personal staging habit since ~2026-07-28, not a
Wikipedia convention. It can stop without notice — which is an argument for 5.4,
not against 5.1.

### 5.2 Replace the existence gate with a completeness gate

This is a latent bug independent of everything else. Articles are routinely created
weeks early with a fully scaffolded but **empty** bracket: `2026 Adelaide
International – Men's singles` was created 2025-12-16 at 10,473 bytes with
`| draw = 28 | seeds = 8` and every `RD1-teamNN` blank — 27 days out — and was not
filled until 2026-01-10 (−2 d). Same at Hong Kong (created −17 d, filled −2 d),
Brisbane (−3 d, −2 d), Madrid (−8 d, −2 d), plus born-as-stub cases (Monte-Carlo
1,837 B → 18,482 B five minutes later). **Creation time varies wildly; fill time is
invariant at −2/−3 days.** Gate on
`named R1 slots + Q-marked slots == draw_size − byes`, byes being the absent RD1
slot ids. Chengdu right now: 20 named + 4 `Q` = 24 = 28 − 4. ✓

### 5.3 Poll from start−3 d, and widen the main-article parse

`2026 Chengdu Open` (created 2026-08-28T11:57Z) and `2026 Hangzhou Open`
(12:08Z) have carried since birth `| draw=28S / 16D` (⇒ four byes to seeds 1–4), a
seeds wikitable (country / player / rank / seed 1–8), and an "Other entrants"
section listing wildcards, the Next Gen entry, four qualifier placeholders and
withdrawals→replacements. **`fetch_event_dates` (`scraper.py:1105`) already fetches
exactly this wikitext and reads only dates from it.** Widening that parse gives
`draw_size`, byes and seeds ~26 days early — more than any paid route offers.
Missing: slot order and the ~12 unseeded direct acceptances, so this alone does not
release a draw. Coverage: 41 of 46 2026 ATP main articles carry a numeric `draw=`,
but formats are messy (`28S / 16D`, `32{{tooltip…`, a combined-event form carrying
both tours) and five lack it entirely — usable, not universal, and it needs a tour
tag for combined events.

### 5.4 The durable authority: the official ATP draw sheet

`protennislive.com/posting/{year}/{atp_id}/mds.pdf` — **confirmed live today**:
`.../2026/7581/mds.pdf` returned HTTP 200, 115,787 bytes,
`Last-Modified: Mon, 21 Sep 2026 09:06:34 GMT`. Carries slot number 1..N, the
literal `Bye`, `Qualifier` placeholders, seed in its own column, `SURNAME, Given`,
IOC nationality, the full entry-code set, and footer sections (Last Direct
Acceptance / Seeded Players / Alternates-Lucky Losers / Withdrawals).
`32 − 4 byes = 28`, matching our DB exactly.

Why this is the right fallback and not a new dependency: it is the **same host and
the same fetcher** as the `op.pdf` job (`order_of_play.py:58`), keyed by an id we
already store for 58/58 men's 2026 draws, parsed by machinery
(`oop_parser.py`) that already reads seed marks and entry designations off this
host's sheets. **The release signal is free too:** pre-release the same stable URL
returns 200 with a ~2.6 KB one-pager reading `-Tournament Information Not Yet
Available-`, so the placeholder→real flip *is* the draw-release event, with no
discovery needed.

Three cautions. (a) Two of three fetches returned **HTTP 429 with
`cf-mitigated: challenge`**, reproduced with both a bot UA and a full Chrome header
set — so it is egress-IP reputation, not UA-dependent; the same URL served 200 ~12
minutes later. Pace it on the existing `op.pdf` budget and retain last-good bytes
on 429. (b) It is a PDF: machine-readable *shape*, not machine-readable *format*.
(c) The file is **live-overwritten**, so later fetches also carry scores and winners
— which must never be read, per the Wikipedia/Sofascore division of authority.

The official JSON does exist (`api.protennislive.com/feeds`, with `GET /Draws`,
`/PlayerList`, swagger at `/feeds/swagger/index.html`) but requires a per-tournament
operator bearer token; this project has already observed 401. Not free, not
available. `atptour.com` is **not** the answer and was not probed: challenge-gated
including its JSON, no `__NEXT_DATA__`, only stealth Playwright has ever passed.

### 5.5 Read `teamSeed` off the cuptree we already fetch

The single cheapest lead found. `_field_of` already GETs
`/unique-tournament/{uid}/season/{id}/cuptrees` for every draw, and
`_main_draw_teams` reduces each participant to `id`, `name`, `country` and `type`,
dropping the rest of the team object on the floor. A third-party slam-bracket
project reports that the cuptree participant carries **`teamSeed`**, valued
`"1"`…`"32"` or `"Q"`/`"WC"`/`"LL"` — i.e. seed and entry type in Sofascore's own
payload, multiplexed the same way Wikipedia's seed column and Flashscore's `HI`
field do it.

If true, this is seed and entry type for every resolved draw at **zero additional
requests**, from a source we already pace, already trust for names
(`DrawEntry.sofa_name`) and already joined on by id. It would **not** give byes or
bracket position, so it does not replace anything in §5.1–5.4 — but it is a strong
second opinion on two fields Wikipedia is currently the sole authority for, and the
owner's standing direction is to demote Wikipedia wherever possible.

Unverified here, deliberately: confirming it costs one request against an
already-resolved draw (§6). Do not build on it before that request.

### 5.6 Not needed, and one genuinely open item

One subagent twice recommended adding `NG` (Next Gen) to the entry-type enum after
finding `RD1-seed11=NG` in the Chengdu draft. **`NG` is already in `ENTRY_TYPES`
(`scraper.py:32`)**, added after Delray Beach 2026. Flagged so it does not get
"fixed" twice. The genuinely open item: the official sheets' code set is
`A, ALT, JE, JR, LL, NG, PR, Q, Q/LL, SE, WC` — wider than our seven. If 5.4 is ever
built, `A`, `JE` and `JR` need a decision (most likely: map `A`→`Alt`, ignore the
junior codes on a tour main draw).

## 6. What I could not determine, and the cheapest experiment for each

Settled during the investigation and therefore removed from this list: the
protennislive path (confirmed 200), the `Draft:`-redirect mechanic (confirmed), and
Wikidata (confirmed: `draw_size` post hoc only, no bracket).

| Open question | Settling experiment |
|---|---|
| Does `flashscore4`'s draw response carry `seed`, an entry type, a slot index? (undocumented on every Flashscore route) | **One** free-tier `GET /api/flashscore/v2/tournaments/draw` against a tournament already in our DB with known entry types — Winston-Salem 2026 M (draw 121, 64-draw, Q/WC/LL present) — and diff the payload keys against `DrawEntry`. The request goes to `flashscore4.p.rapidapi.com`, **not** a Flashscore host, so it is safe under the no-contact rule. Free, one request, definitive. |
| Does it represent a first-round bye? | Same call against a **28-draw** (Los Cabos 2026, draw 117). If it returns 32 round-1 matches with four one-sided ones, it cannot distinguish bye from unpublished, and the answer is no. |
| **Is the Flashscore bracket populated at draw release (≈2 days out)?** No route documents this, and the day feed's −7…+1 window says no for that path. | Poll `flashscore4`'s free tier once a day through the next ATP 250 week against an event whose `bracket_first_seen_at` we record independently from Wikipedia, and compare the dates. ~7 free calls, no new code. Answers brief question 1 directly. |
| Does `zen-studio/flashscore-tennis-api`'s `/draw` really return `seed`, `entry_status` and a bye, and what values does `entry_status` take? | Its `/draw` is free-tier: one run against Winston-Salem 2026 and one against a 28-draw. The same two payloads settle both the field question and the actor's credibility. |
| Does Matchstat's `draws` endpoint return anything for an **unplayed** draw? Its sample shows only completed matches, and its pre-tournament claim is stated but not demonstrated. | One free-tier call (50/day) against Chengdu or Hangzhou 2026 today. If it returns an empty `singles` array, the pre-draw claim is marketing. |
| **Does Sofascore's `cuptrees` participant carry `teamSeed`** (`"1"`…`"32"`, `"Q"`, `"WC"`, `"LL"`), as a third-party bracket project reports? This is the highest-value open question in the list — see §5.5. | One targeted GET of an already-resolved draw's cuptree, then `grep -i -e teamSeed -e seed` on the JSON. **One request**, inside existing pacing, no bulk collection. If it is there, two fields become free. |
| Does Flashscore's `dr_` feed really encode a bye as a blank-named `PA` slot, and is the `PA` index really the bracket slot? | **Cannot be settled without hitting Flashscore, so leave it unsettled.** The public GitHub fixture that proved `HI`/`AI` is a 128 Slam draw with no byes; a 28-draw fixture would be needed and none is published. This is the question that would have to be answered to adopt, and the constraint correctly forbids answering it. |
| Does the WTA `matches` feed express a first-round bye and a stable slot order? (It has `SeedA`/`SeedB`, `EntryTypeA`/`EntryTypeB`, `DrawLevelType` per `wta_feed.py`) | One request to `api.wtatennis.com/tennis/tournaments/1024/2026/matches` (Korea Open, 32-draw, no byes) and one to a 28-draw WTA 500, then count round-1 rows. Already-wired code, public endpoint. Note `wta_live_scoring_id` is set for only 16/98 2026 tournaments, so id coverage would need widening either way. |
| How reliable is the `Draft:` habit across the whole calendar rather than this one editor's events? | Query the Wikipedia API for `Draft:` pages matching `{year} * – Singles` across the 2025 and 2026 seasons and measure how many mainspace articles had a draft predecessor. Read-only, free. |
| Do api-tennis.com's `seed` strings include `LL`/`ALT`/`PR`; does `source` actually read `draw_feed` for a 250 two days out; and can `get_players` expand `"D. Medvedev"` to a name our matcher can use? | Its 14-day trial, one `get_draw` against Chengdu 2026 plus one `get_players`. These three answers together decide whether the only complete paid route is usable at all. Only worth spending if 5.1–5.4 all fail. |
| Does Sportradar's `bracket_number` survive an unplayed draw? | Reported ~1,000-query trial (**that figure is from a search summary, not verified**). Low priority — it has no bye field either way. |
| Whether any wrapper's own terms permit redistributing derived draw shape | **Could not confirm.** Needs the wrapper's terms read in full — and for Apify, the actor author's terms as well as Apify's. |
| `ws.protennislive.com/…/GetOOPXML.aspx` — does a legacy XML draw feed still exist? | Appears in 2017-era third-party code; **could not confirm** within the 3-request budget for that host. One `HEAD`, if 5.4's PDF parsing ever proves painful. |
