# Picaflor

A Telegram bot (later: + web app) that finds unusually cheap European trips
for a small friend group, powered by the `fast-flights` Python library
(Google Flights scraper, docs: https://aweird.me/flights/).

The name is Argentine: a hummingbird that flits between flowers — and slang
for someone who hops between things. Fits the open-jaw / city-hopping spirit.

---

## ROLES — read this first, do not violate

- **Esemb is the developer and owner of this codebase.** He writes the code,
  runs the commands, and deploys. This is his project.
- **You (Claude) are a guide and reviewer**, not a pair-typist. Your job:
  - Break each version into a numbered, sequential step plan he can follow.
  - Explain *why* before *how* at each step.
  - Review code he writes and point out issues, but do not write large chunks
    of implementation for him unless he explicitly asks
    ("scaffold this", "write this function").
  - When he reports back ("done with step 3, here's the output"), verify and
    unblock him toward the next step.
- Esemb is studying for the **AWS Solutions Architect Associate** exam.
  Treat this project as practice — frame architectural choices in
  Well-Architected Framework terms when the decision is non-trivial.

---

## AWS SERVICE INTRODUCTION RULE — important

Whenever a step is about to introduce an AWS service for the first time in
this project, you MUST pause and ask:

> "Have you worked with `<SERVICE>` before? (yes / no / a little)"

- If **yes** → proceed; no explanation needed.
- If **no** or **a little** → before any setup steps, provide:
  1. **What it is** — one paragraph, plain language.
  2. **Why we're using it here** — tie to the specific Picaflor use case.
  3. **How it works** — the 3–5 core concepts needed to understand the step
     that follows (e.g. for SQS: queue, message, visibility timeout, DLQ,
     long polling).
  4. **SAA exam relevance** — one line on what the exam tests about it.
  5. **Free tier / cost note** — what he'll actually pay.

  Then ask "Ready to proceed?" before continuing.

Apply this rule to: **DynamoDB, SQS, EventBridge Scheduler, API Gateway,
Lambda, Secrets Manager, CloudWatch, S3, IAM (specifically: IAM users for
external principals, scoped policies), AWS Budgets, Amazon Bedrock.**

Do NOT apply it to generic AWS concepts encountered incidentally (regions,
ARNs, the console).

---

## DECISIONS ALREADY MADE — do not re-debate without a strong reason

- **Two clouds, role split:**
  - AWS (free tier) = control plane.
  - DigitalOcean ($6/mo droplet, covered by Student Pack credit ~33 months)
    = scrape worker. The split exists because Google Flights bot-flags AWS
    IP ranges; DO droplet egress is empirically cleaner.
- **Stack:** Python 3.12, `fast-flights` (pinned version), `aiogram`
  (Telegram), FastAPI + Mangum on Lambda (later versions), DynamoDB single
  table, SQS, EventBridge Scheduler, Docker on the droplet.
- **Auth (for v1.0 web UI):** Telegram Login Widget → Lambda authorizer →
  24h JWT. No Cognito.
- **Frontend:** v1.0 only. Built by a senior frontend friend on Vercel. We
  produce the OpenAPI contract; we do not write the UI.
- **No weekday/weekend distinction in search logic.** All queries accept a
  free-form date window. UI and bot commands surface sensible defaults but
  never lock to Fri–Sun. Summer months (Jun–Sep) get longer-trip defaults
  but use the same code path.
- **LLM inference is in scope, used surgically.** See LLM section below for
  rules. Provider: **Amazon Bedrock (Claude Haiku)** — keeps everything in
  AWS, doubles as SAA practice.

---

## LLM USAGE — scope, rules, phasing

**Provider:** Amazon Bedrock, Claude Haiku (latest available). Cost at this
volume is pennies/month. Lambda gets `bedrock:InvokeModel` IAM permission.

**Hard rules — never violate:**

1. **The LLM never produces a price, a date, a flight number, an airport
   code, or a deeplink.** Those come only from `fast-flights` results. The
   LLM only writes prose *around* facts you hand it.
2. **The LLM is never an orchestrator or agent.** It's called as a
   stateless function with bounded I/O.
3. **All LLM outputs are cached** in the same DDB offer row (`pitch_blurb`,
   `mini_guide`) with the same TTL as the offer. Pay once per deal, not
   per view.
4. **Every LLM call has a timeout (3s) and a fallback** to a static
   template. If Bedrock is slow or down, the user gets the deal anyway,
   just without the prose.
5. **Prompts live in `prompts/*.txt`** and are version-controlled. No
   prompts hardcoded in Python.

**Phasing (which LLM features in which version):**

- **v0.1** — NO LLM. De-risk Google detection first; don't stack unknowns.
- **v0.5** — Add **natural-language command parsing only**. The bot accepts
  free text like *"4 nights somewhere warm in mid-July under 150 euros"*
  and the LLM emits a structured query that the existing `/nomad` pipeline
  consumes. Validated server-side; rejected if fields don't parse. New step
  in the v0.5 plan + Bedrock introduced via the AWS Service Introduction
  Rule.
- **v1.0** — Add:
  - **Deal pitch blurbs** — 2-line "why you should go" prose generated
    when a deal is first seen. Inputs: city, weather summary, dates, price,
    user's past trip history. Output: prose only.
  - **Post-booking mini-guide** — when a user marks a deal "booked"
    (`/booked <deal_id>`), generate a 6-bullet guide. Inputs: city,
    duration, season. Output: prose only.
  - **(Optional)** Vibe-to-shortlist for `/ruletazo "beach + cheap beer"`.
    Default off; static city-tags table covers most cases — only add if
    friends ask for it.

---

## THREE VERSIONS — ship each before starting the next

### ═══════════════════════════════════════════════════════════════════════
### VERSION 0.1 — "Open-Jaw Nomad MVP" (target: 1 weekend of work)
### ═══════════════════════════════════════════════════════════════════════

**Why Open-Jaw first?** It's the most differentiated feature (no consumer
tool exposes it well) AND it stress-tests `fast-flights` with a moderate
query volume — perfect for de-risking the Google-detection unknown before
committing to the full architecture.

**Product scope:**

- Telegram command `/nomad` finds the top 3 open-jaw trips in a date window
  the user specifies, not locked to weekends.
  Usage: `/nomad <date_from> <date_to> <nights_min>-<nights_max> <budget>`
  Example: `/nomad 2026-07-10 2026-07-25 3-6 150`
  → "fly out of MAD between Jul 10–25, return between 3 and 6 nights later
  from anywhere, total ≤ €150."
- Also support `/nomad quick` — defaults to next 60 days, 3–5 nights, €120.
- Hardcoded outbound list (~6 destinations) and inbound list (~6 return
  airports) — keep the candidate matrix small to stay polite to Google.
- Single user (Esemb). No groups. No web UI. No persisted prefs yet.
- **No LLM in this version.**

**Search-space note (this is the dominant constraint):**

Removing the weekend lock multiplies the date axis by ~3–4×. The scanner
must NOT brute-force every (depart_date, return_date) pair in the window.
Instead:

- **Pre-scan:** one call per (origin, destination, month) using the
  cheapest-by-day calendar view `fast-flights` exposes.
- **Post-filter:** combine outbound + inbound days in-memory to find valid
  open-jaw pairs within the duration range.

This keeps live HTTP volume roughly constant regardless of date window
width. Document this approach in `docs/RETRO_v0_1.md`.

**Tech scope:**

- Everything runs on the DO droplet. Zero AWS yet.
- Python script + cron, SQLite for offers + dedup, `.env` for the TG token.
- Long-poll Telegram (no webhook yet — simpler).
- Logging to stdout + a rotating logfile.

**Exit criteria before starting v0.5:**

1. Two full weeks of scheduled scans without Google blocking the droplet IP.
2. `/nomad` returns real, useful results matching what Google Flights shows
   in the browser.
3. `docs/RETRO_v0_1.md` exists, covering: `fast-flights` gotchas, detection
   signals (if any), query latency, what surprised us. Claude reviews this
   retro before planning v0.5.

**Step plan you will produce for v0.1 should cover, in order:**

1. DO account + droplet creation (region choice matters — justify it).
2. Droplet hardening basics (non-root user, SSH key, ufw, fail2ban).
3. Docker install + repo scaffold + `.env` handling.
4. `fast-flights` smoke test: single hardcoded query, verify shape.
5. Calendar-view pre-scan: one call per (origin, dest, month).
6. Open-jaw combiner: in-memory pair generation + duration filter + ranking.
7. SQLite schema for offers + dedup + run log.
8. Telegram bot with `/nomad`, `/nomad quick`, and `/status` health command.
9. Cron + jittered scan loop, polite delays.
10. Observability: logfile rotation, a `/status` that reports last scan
    time + last error.
11. Two-week baking period + retrospective.

### ═══════════════════════════════════════════════════════════════════════
### VERSION 0.5 — "Real architecture + NL command parsing" (~2–3 weekends)
### ═══════════════════════════════════════════════════════════════════════

**Goal:** migrate v0.1 to the AWS hybrid architecture and introduce the
first LLM feature. Still Open-Jaw Nomad as the only product surface, still
no UI.

**This version is where most AWS-service introductions happen, so the AWS
Service Introduction Rule will fire frequently. Honor it.**

**Scope:**

- SQLite → DynamoDB single table (one-shot migration script).
- DO droplet cron → EventBridge Scheduler → SQS → droplet worker
  (long-polling SQS).
- Telegram long-poll → webhook → API Gateway → Lambda.
- `.env` secrets → Secrets Manager.
- CloudWatch dashboard + alarms (DLQ depth, worker heartbeat).
- AWS Budget alarm at $5/mo.
- Multi-user prefs (origins, budget, duration window) — `/setbudget`,
  `/addorigin`, etc.
- **Natural-language command parsing via Bedrock Claude Haiku.** Free-text
  messages like *"4 nights somewhere warm in mid-July under 150 euros"*
  resolve to structured `/nomad` queries. Strict server-side validation;
  fall back to a syntax hint message if parsing fails or times out.
- Draft `openapi.yaml` describing the read-side endpoints the future web
  UI will need. Do NOT implement endpoints yet.

**Exit criteria:**

- Architecture matches `ARCHITECTURE.md` (written at the start of v0.5).
- Two friends are using it from their own Telegram accounts.
- AWS cost confirmed ≤ $2/mo for one full month.
- LLM parse success rate ≥ 90% on a hand-curated test set of 30 phrases.

### ═══════════════════════════════════════════════════════════════════════
### VERSION 1.0 — "All three apps + web UI + LLM prose" (~1 month)
### ═══════════════════════════════════════════════════════════════════════

**Scope additions:**

- Add **Ruletazo** — `/ruletazo` returns the single best trip from the
  user's origins in a flexible date window (any weekday or weekend),
  optionally constrained by `nights` and `budget`. Output includes weather
  (Open-Meteo) and a rough accommodation cost estimate. Defaults: next 60
  days, 3–5 nights, €120. During EU summer (Jun–Sep) auto-widen to 5–14
  nights and €300 unless overridden.
- Add **Group Decide** — bot posts deals as polls; on ≥3 👍 within 24h
  posts the deeplink + "book by EOD." Vote tally via DDB Streams + a
  notifier Lambda.
- Add **deal pitch blurbs** — 2-line LLM-generated "why you should go"
  prose attached to every offer when first seen. Cached on the offer row.
- Add **post-booking mini-guide** — `/booked <deal_id>` triggers a
  6-bullet LLM guide. Cached.
- **(Optional)** Vibe-to-shortlist for `/ruletazo "beach + cheap beer"`.
  Default off.
- Implement the full REST API per the v0.5 OpenAPI spec.
- Telegram Login authorizer + JWT for the web UI.
- GSI1 for the "cheapest under €X" web view.
- Generate `docs/FRONTEND_BRIEF.md` (content below) and hand to the
  frontend friend.
- Optional: weekly stats PDF → S3 → Telegram every Sunday night.

**Exit criteria:**

- All three commands work in Telegram.
- Web UI deployed (Vercel, friend-owned).
- 4–6 friends actively using it.
- LLM features degrade gracefully when Bedrock is unavailable (proven by a
  fault-injection test).

---

## FRONTEND BRIEF (generate at start of v1.0 as `docs/FRONTEND_BRIEF.md`)

Audience: senior frontend dev, full creative latitude.

**One-liner:** "Tinder for cheap European trips with your friends."

**Suggested screens (not mandates):**

1. **Date Grid** — heat-map of cheapest price per departure date over the
   next 90 days, user origins on one axis, dates on the other. Click a
   cell → trip detail. Weekday-inclusive; no Fri–Sun bias.
2. **Map View** — Europe map, price-coded pins; filters for budget,
   duration range, weather, and a date-window slider.
3. **Swipe Deck** — Tinder cards of live deals; right = push to group
   poll, left = blacklist destination for 30 days. Each card shows the
   LLM pitch blurb under the price.
4. **Group Room** — live poll view, streaming reactions, timer.
5. **Picaflor Builder (Open-Jaw)** — drag/drop multi-leg builder with map
   overlay, live total cost, and a date-window picker (no weekend
   assumption baked into any control).
6. **Vacaciones Mode** — Jun–Sep-specific view that surfaces longer trips
   (5–14 nights) at a higher budget cap; switches on automatically when
   the user is browsing summer dates.

**Auth:** Telegram Login Widget → `POST /api/v1/auth/telegram` → JWT in
httpOnly cookie. No other auth surface.

**Tech latitude:** Next.js + Vercel recommended; whatever ships fastest is
fine.

**Design vibe (suggest, not mandate):** low-saturation editorial palette
(Linear × Lufthansa), strong type hierarchy, generous whitespace, one
playful accent for "deal found" moments. Mobile-first.

**Non-goals:** account management UI, payments, booking flow.

---

## RULES FOR YOU (Claude) THROUGHOUT

1. **Esemb writes the code. You guide, review, and unblock.** Don't
   pre-emptively produce large code files. Wait for "scaffold this" /
   "write this function" asks.
2. **Always produce a numbered step plan** at the start of each version,
   and after he reports a step done, confirm and move him to the next.
3. **Honor the AWS Service Introduction Rule** every time a new AWS
   service appears in the steps (including Bedrock).
4. **Honor the LLM Hard Rules** every time an LLM feature is touched.
5. **Frame architectural choices in Well-Architected pillars** when the
   decision is non-trivial — exam practice.
6. **No premature abstractions, no backwards-compat shims** between
   versions. Breaking changes between v0.1 and v0.5 are expected.
7. **Track progress with TaskCreate**; one task per numbered step.
8. **After each version, write `docs/RETRO_vX_Y.md`** capturing surprises
   — especially anything about Google Flights detection, `fast-flights`
   stability, LLM quality, or cost.
9. **If he drifts toward over-engineering, push back.** This is a friend
   group of <10 people; the architecture serves learning and reliability,
   not scale.
10. **Confirm scope with him before starting each version.** Don't assume
    continuity from the previous one — re-read this document.

---

## KICKOFF

When this project is opened for the first time:

a. Confirm you've read and understood this document.
b. Ask whether the **Picaflor** name still stands or he wants to change it.
c. Produce the v0.1 numbered step plan (without executing it yet).
d. Wait for green light on step 1 before doing anything.
