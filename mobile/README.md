# Upset Alert — mobile

React Native / Expo client. Talks to the same production API as the website
(`https://upsetalert-api.upsetalert.ca`), JWT bearer only.

**Nothing here can affect the live site.** Cloudflare Pages builds `frontend/`
and `deploy.sh` rebuilds the backend only when `backend/`, `docker-compose.yml`
or a Dockerfile changes. This directory is invisible to both.

## Running it

The dev server lives in its own tmux session so it survives Claude restarts,
`/exit`, and detaching:

```sh
tmux attach -t expo      # watch it;  Ctrl-b d to detach
# if it isn't running:
tmux new-session -d -s expo -c ~/Documents/Claude/Projects/TennisFantasyLeague/mobile
tmux send-keys -t expo 'npx expo start' Enter
```

Then open `exp://192.168.1.111:8081` in Expo Go — phone and server on the same
Wi-Fi. **Prefer LAN over `--tunnel`:** ngrok's edge publishes AAAA records that
are unreachable from this network, and iOS prefers IPv6, so tunnel URLs hang on
"Opening project…" while LAN answers in ~100 ms. LAN is also stable across
restarts; the ngrok subdomain is not.

## SDK 54, deliberately

Expo Go supports exactly ONE SDK, and the iPhone this is developed against runs
Expo Go 54 with no App Store update available. A newer project answers every
scan with "Project is incompatible with this version of Expo Go". Check what the
phone actually reports before changing it — it announces itself on every scan:

```sh
curl -s http://127.0.0.1:4040/api/requests/http | grep -o 'Exponent/[0-9.]*'
```

A **development build** carries its own runtime and ends this constraint. That
is also the point at which Live Activities become testable, since Expo Go
cannot host a widget extension.

## Layout

```
app/                       expo-router; the file tree IS the URL tree
  _layout.jsx              providers + stack
  index.jsx                leagues you're in
  sign-in.jsx  status.jsx
  league/[id]/index.jsx    that league's draws
  league/[id]/draw/[drawId]/index.jsx   standings
  league/[id]/draw/[drawId]/picks.jsx   your picks vs results
api.js       transport; errors carry .status and .offline
session.js   the JWT, in the Keychain
auth.jsx     who is signed in; owns the 401 rule
useApi.js    small keyed cache (see below)
scoring.js   the comparisons that decide what the screens say
theme.js  ui.jsx
```

## Decisions worth not re-litigating

**expo-router, not react-navigation.** Tapping a Live Activity has to open one
particular match. File-based routing makes that a URL (`upsetalert://…`) rather
than hand-rolled navigation state, and the website already has `?user=` and
`?league=` deep links to mirror.

**No React Query.** `useApi.js` is the ~50 lines of it we use: keyed cache,
in-flight dedupe, explicit invalidation. It does not refetch on focus, retry, or
garbage collect — when those are wanted, that is the moment to add the real
library, not before.

**`react-dom` + `react-native-web` are installed but unused at runtime.**
expo-router peer-depends on them through vaul/Radix. Without them every
`npm install` fails ERESOLVE — which is what blocked eslint. They satisfy the
peers honestly; `--legacy-peer-deps` would only hide the problem.

**Only a 401 signs anyone out.** A network failure is not a logout. Tokens are
year-long and rolling, so a session that looks broken is nearly always
transport, and clearing it turns a five-second outage into a re-authentication.
`api.js` fires the handler only for a request that actually carried a token —
otherwise a wrong password (also a 401) would read as "your session ended".

**Standings are never re-sorted on the client.** The server orders by total,
then by points in the latest rounds first (Final → SF → QF → …). That tiebreak
is lexicographic over the round vector, not a weighted sum.

## Checks

```sh
node scoring.test.mjs    # the rules that fail silently
npx expo lint            # 0 problems expected
npx expo-doctor          # 18/18
npx expo export --platform web --output-dir /tmp/webexport
```

That last one is the useful one: `web.output` is set to `static`, so the export
PRERENDERS every route, which executes every screen. It is the closest thing to
running the app without a device — a crash in any screen fails the export.
Routes with no session render their loading state and are legitimately textless.
