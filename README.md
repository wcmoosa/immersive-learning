# Meridian Analyst — Market Analysis & Forecasting Simulation

A showcase MVP of AI-supported immersive learning, built for Silverse's pilot
with **Regent Business School**. A student plays a junior investment analyst
managing **R1,000,000** of a client's money across a fictional South African
share market (the *Meridian Exchange*) over **four quarterly rounds**: read the
market brief, record a forecast, allocate the portfolio, see rule-based
explainable results, receive live AI coaching, reflect, repeat.

This is a deliberate **throwaway showcase** — good enough to demo the value of
the contracted pilot, without carrying the pilot's engineering obligations.

## What it demonstrates

- **Multi-round decision play** with a structured forecast → allocate → results loop.
- **Deterministic, explainable outcomes** — every price move and score carries a plain-language "why". The AI never invents outcomes or scores.
- **Live AI coaching** (OpenAI) grounded strictly in the student's own decisions, with **authored fallbacks** so the demo never stalls if the API is slow or absent.
- **A transparent composite performance model** (decision quality · reflection quality · outcome), a **client-trust** gamification score, and a **class leaderboard**.
- **A read-only lecturer view** of the cohort: progress, decisions, reflections, and AI feedback.

## Run it (one command)

```bash
docker compose up --build
```

Then open **http://localhost:8010**. The database is seeded automatically on
first boot (demo accounts + a fictional cohort for the leaderboard).

> Host port **8010** maps to the container's 8000 — chosen to avoid clashing
> with other local apps that commonly use 8000.

### Demo accounts

All accounts use the password **`demo`**.

| Username   | Role     | Use for                                   |
|------------|----------|-------------------------------------------|
| `student`  | student  | The live playthrough (starts fresh)       |
| `thabo`    | student  | An alternate student account              |
| `aisha`    | student  | An alternate student account              |
| `lecturer` | lecturer | The read-only cohort view                 |

The leaderboard and lecturer view are pre-populated with five fictional
completed runs (Nomvula, Sipho, Fatima, Johan, Lerato) so they look alive
before the live run.

### Reset between rehearsals

```bash
docker compose exec app python -m app.seed reset
```

Restores clean demo state (accounts + fictional cohort, no live runs). For a
completely fresh volume: `docker compose down -v` then `docker compose up`.

## Live AI coaching (optional)

The demo runs fully **without** any API key — coaching falls back to authored,
pre-approved content. To enable live OpenAI coaching:

```bash
cp .env.example .env
# then edit .env:
#   OPENAI_API_KEY=sk-...
#   OPENAI_MODEL=gpt-4o-mini   (confirm the current cost-efficient chat model)
docker compose up --build
```

`.env` is gitignored and never committed. Feedback generation has a 10-second
timeout with one retry, then falls back to authored content automatically.

## Environment variables

| Variable         | Default                        | Purpose                                              |
|------------------|--------------------------------|------------------------------------------------------|
| `OPENAI_API_KEY` | *(unset → fallback mode)*      | Enables live AI coaching                             |
| `OPENAI_MODEL`   | `gpt-4o-mini`                  | Chat model for coaching/reflection prompts           |
| `SESSION_SECRET` | dev placeholder                | Signs the session cookie                             |
| `DATABASE_URL`   | `sqlite:////app/data/app.db`   | SQLite location (set in `docker-compose.yml`)        |
| `CONTENT_PACK`   | `content/scenario_meridian.yaml` | Path to the scenario content pack                  |

## Local development (without Docker)

Requires **Python 3.12**. From a fresh environment:

```bash
pip install ".[dev]"
python -m app.seed reset          # create ./data/app.db and seed
uvicorn app.main:app --reload     # serves on http://localhost:8000
pytest                            # run the test suite
```

## Project layout

```
app/
  main.py       FastAPI app, routes, session auth, run state machine
  models.py     SQLite ORM models
  db.py         engine + session
  auth.py       cookie-session auth helpers
  content.py    scenario content pack loader + validation
  engine.py     deterministic simulation engine (pure functions)
  scoring.py    transparent composite performance model
  feedback.py   AI coaching service (OpenAI + canned fallback)
  seed.py       seed / reset CLI
  seed_demo.py  fictional completed cohort
  templates/    Jinja2 pages
  static/        vendored htmx + Chart.js + CSS (offline-safe)
content/
  scenario_meridian.yaml   the authored synthetic market
docs/
  demo-script.md           presenter walkthrough
wheelhouse/                vendored dependency wheels (offline docker build)
```

## Notes on the build

Dependencies install from a **vendored wheelhouse** so `docker compose up`
works fully offline — no PyPI access needed at build time. This keeps the demo
resilient on any network. See `Dockerfile`.

---

*Synthetic market — not investment advice. All companies, prices, events, and
the client are fictional.*
