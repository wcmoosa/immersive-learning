# Presenter walkthrough — Meridian Analyst

A ~10-minute live demo for the Regent Business School management team. The goal
is to **show the value** of AI immersive learning as an alternative to
Capsim/VikasNiti-style tools, and to narrate how the contracted pilot would
work — capability for capability.

> Rehearse once end-to-end before the room. Everything below runs on a laptop
> with `docker compose up`; no internet is required (AI coaching falls back to
> authored content if there's no key or network).

## 0. Before the room

```bash
docker compose up --build          # first run builds; later runs are instant
# open http://localhost:8010
```

If you rehearsed already and want a clean slate:

```bash
docker compose exec app python -m app.seed reset
```

Have two browser windows ready (or one normal + one private/incognito):
- **Window A** — logged out, ready to sign in as `student`.
- **Window B** — logged in as `lecturer`.

All passwords are `demo`.

## 1. Frame it (1 min)

> "Regent's pilot is about experiential, decision-based learning. Instead of a
> quiz, the student *does the job*. Here they're a junior investment analyst
> managing a real client's money. Watch how every outcome is explained, how AI
> coaches without ever grading, and how the lecturer sees everything."

Point out the framing: this mirrors a Capsim-style decision environment, but
**formative-first** and **explainable** — the two things the pilot promises.

## 2. The student plays a round (4–5 min)

Sign in (Window A) as **`student` / `demo`** → *Start simulation*.

1. **Brief** — read the market brief and the *Market snapshot* table.
   > "The student gets real analyst inputs: price history, sector news, an
   > economic backdrop — load-shedding, and later a rate hike and a supply shock."

2. **Forecast** — call each sector up/flat/down and type a one-line rationale.
   > "We capture their *reasoning*, not just their numbers — and we score
   > whether their allocation actually matches their forecast."

3. **Allocate** — split the R1,000,000. Watch the **live total** update as you
   type; note the **mandate reminder** (max 40% per share, keep 10% cash).
   > "The client has a mandate. Break it and the score — and the client's trust
   > — will react."
   Submit at 100%.

4. **Results** — this is the key moment:
   - Portfolio vs benchmark, per-share moves, **each with an authored "why"**.
     > "The outcome engine is **rule-based**. The AI did *not* invent these
     > numbers — that's the academic-integrity point the pilot depends on."
   - The **client-trust gauge** moves with a plain-language explanation.
   - The **advisor's feedback** panel loads in-fiction ("your advisor is
     reviewing…") then shows AI coaching.
     > "This coaching is generated live from *their* decisions — but it never
     > touches the score. AI writes words; rules decide marks."

5. **Reflect** — answer the reflection prompt (it references their round).
   > "Reflection is part of the learning loop and part of the composite model."

Play **one round in full**, then either play through to the summary or jump
ahead by mentioning the remaining rounds add a **rate hike (round 2)** and a
**mining supply shock (round 3)**.

## 3. The payoff — summary & leaderboard (2 min)

At the **final summary**:
- Total return vs benchmark, final client trust, the **round-by-round journey** chart.
- The **composite performance breakdown** — decision quality, reflection
  quality, outcome — each with its weight and its "why".
  > "Every component is transparent, rule-based logic — exactly the
  > 'academically approvable' model in the proposal. The AI's indicative
  > reading of the reflection is shown beside it, clearly labelled, and never
  > enters the score."

Open the **Leaderboard**:
> "A class leaderboard by composite score — decisions and reasoning, not just
> luck. Every student faces the same authored market, so it's fair."

## 4. The lecturer view (1–2 min)

Switch to **Window B** (`lecturer`).
- The **cohort table**: who's started, who's finished, composite, trust.
- Click **View detail** on a student:
  > "The lecturer sees every decision, every reflection, and the AI feedback
  > that was given — read-only, for oversight and assessment. This is the
  > academic/lecturer view the pilot calls for."

## 5. Close (1 min)

> "What you've seen: multi-round decision play, explainable rule-based
> outcomes, live AI coaching that never grades, a transparent composite model,
> and a lecturer oversight view — the shape of the contracted pilot, in a
> working demo. The pilot build hardens this into the platform."

### The fallback story (if asked, or if the network dies)

> "If the AI is slow or unavailable, coaching falls back to pre-authored,
> human-approved content — the round still completes. The *outcomes and scores
> never depend on the AI at all*; they're deterministic. That's deliberate:
> it's what makes the model defensible for academic assessment."

## Reset checklist between runs

```bash
docker compose exec app python -m app.seed reset   # clean cohort, no live runs
```

Then sign in fresh as `student`. The five fictional analysts remain on the
leaderboard so it always looks populated.
