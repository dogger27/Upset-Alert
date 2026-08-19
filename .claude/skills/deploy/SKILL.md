---
description: Deploy Tennis Fantasy League changes to the live server (upsetalert.ca)
---

# Deploy — Tennis Fantasy League

Pushes local changes to GitHub and deploys to the Jupiter production server.

## Rules

- **You are already on the production host.** Do not wrap anything in `ssh jupiter`.

- **Never push directly to main.** All changes must go through a feature branch first.
- The live site is at upsetalert.ca — treat every deploy as production. upsetalert.paulwiens.com is decommissioned.
- Backend rebuild (docker compose) is only needed when `backend/` files changed. Frontend build only when `frontend/` files changed.

## Step 1 — Assess local state

Run these in parallel:

```bash
git status
git branch --show-current
git log --oneline -5
```

Determine:
- Are there uncommitted changes? (`git status`)
- Are we on a feature branch or on main?
- What files changed relative to main? (`git diff --name-only main` if on a feature branch)

## Step 2 — Commit to a feature branch

**If there are uncommitted changes:**

If already on a feature branch (name starts with `feature/`):
```bash
git add <changed files>
git commit -m "Description of changes"
```

If on `main` (or any non-feature branch), create a feature branch first:
```bash
git checkout -b feature/<short-description>
git add <changed files>
git commit -m "Description of changes"
```

Ask the user for a branch name if the changes span multiple concerns; otherwise derive a short name from the changed files (e.g. `feature/draw-header-layout`, `feature/admin-leagues`).

**If there are no uncommitted changes and we're already on a feature branch with commits ahead of main:** proceed to Step 3.

**If there are no uncommitted changes and we're on main with nothing to push:** nothing to deploy — tell the user.

## Step 3 — Push feature branch and merge to main

```bash
# Push the feature branch
git push origin <feature-branch-name>

# Switch to main and merge
git checkout main
git merge --no-ff <feature-branch-name> -m "Merge <feature-branch-name>: <short summary>"
git push origin main
```

## Step 4 — Identify what changed

After merging to main, check what files the feature branch introduced. With a `--no-ff` merge, `HEAD~1` is the old main tip, so this shows exactly what's being deployed:

```bash
git diff HEAD~1 HEAD --name-only
```

Categorise the output:

| Changed path | Action needed on server |
|---|---|
| `backend/app/**` (any `.py` file) | **Full Docker rebuild** — code is baked into the image |
| `backend/requirements.txt` | **Full Docker rebuild** — new dependencies |
| `backend/Dockerfile` | **Full Docker rebuild** |
| `docker-compose.yml` only | **Recreate only** (no rebuild — env/port change, image unchanged) |
| `frontend/**` | **CF Pages auto-deploys** — no manual step needed |
| Memory/skill/config files only | No server action needed |

## Step 5 — Deploy to Jupiter

**Always run first (pull the new code):**
```bash
cd /home/paulwiens/upsetalert/app && git pull origin main
```

**If `backend/app/`, `backend/requirements.txt`, or `backend/Dockerfile` changed — full image rebuild:**
```bash
cd /home/paulwiens/upsetalert/app && docker compose build && docker compose down && docker compose up -d
```
This rebuilds the image with the new Python code and restarts the container. The DB survives because it is bind-mounted from the host.

**If only `docker-compose.yml` changed (no Python code change) — recreate without rebuild:**
```bash
cd /home/paulwiens/upsetalert/app && docker compose down && docker compose up -d
```

**If only frontend files changed — no server action needed.**
Cloudflare Pages automatically builds and deploys from every `git push origin main`.
The build runs on CF's infrastructure (~1–2 min). Do NOT run `npm run build` on Jupiter — it has no effect on what users see.

## Step 6 — Verify

Check the backend is healthy:
```bash
docker compose -f /home/paulwiens/upsetalert/app/docker-compose.yml ps
```

And optionally tail recent logs:
```bash
tail -20 /home/paulwiens/upsetalert/logs/backend.log
```

**Frontend — NEVER request `/assets/*` to verify a deploy. Not once, not after
reading the hash out of index.html, not "once it looks settled".**

A request for a hashed asset that is not on that edge yet is answered with the
SPA fallback — index.html, at HTTP 200 — and `_headers` caches that response
under the `/assets/*` rule. The bundle then serves as `text/html`, every client
fails with *"Expected a JavaScript-or-Wasm module script but the server
responded with a MIME type of text/html"*, and the app does not boot at all.
There is no cache-purge token in this environment, so the only remedy is a new
deploy with new hashes.

This has happened twice. The second time (2026-08-19) was a verification loop
that read the hash *from index.html first* and fetched that — which feels safe
and is not: index.html can reach an edge ahead of the assets it names, and that
window is precisely what poisons the URL.

**Poll a fixed path only.** `/sw.js` and `/theme.js` are never content-hashed:

```bash
# bump SW_VERSION in frontend/public/sw.js as part of the change, then:
until curl -s https://upsetalert.ca/sw.js | grep -q '<new-version>'; do sleep 20; done
```

Verifying the bundle itself is almost never worth the risk. If you truly must,
do it once, by hand, well after the deploy has landed — never in a loop.

Also: never poll for your LOCAL build hash. Cloudflare builds the same commit
independently and produces a *different* hash, so waiting on the filename
`npm run build` printed can never finish.

And a `grep` that matches nothing exits 1, marking a background task FAILED even
when the deploy was fine. Put greps last, or `|| true` them.

## Notes

- **This session runs ON Jupiter — never `ssh jupiter`.** It fails with `Permission denied (publickey,password)`, because the host holds no key authorising itself. Every command here runs locally as written.
- The backend runs in Docker as `app-backend-1`. DB is bind-mounted from host; it survives container restarts.
- `docker-compose.yml` is at `/home/paulwiens/upsetalert/app/docker-compose.yml` (repo root).
- **Frontend is served by Cloudflare Pages** (upsetalert.ca → CNAME → upsetalert.pages.dev). CF Pages auto-builds on every push to main. Running `npm run build` on Jupiter does nothing for users.
- Backend API is at upsetalert-api.upsetalert.ca via Cloudflare Tunnel.
- SSH alias `jupiter` is configured in `~/.ssh/config`.
