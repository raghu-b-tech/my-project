# FanPath

**A multilingual, accessibility-aware navigation concierge for FIFA World Cup 2026 fans.**

Built for PromptWars — *Smart Stadiums & Tournament Operations*.

> ⚠️ Before you push: replace `YOUR_USERNAME` below with your GitHub username so the CI badge resolves.

[![CI](https://github.com/YOUR_USERNAME/fanpath/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/fanpath/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The problem

FIFA World Cup 2026 is the largest edition ever staged — 48 teams, 104 matches, 16 host cities across the United States, Canada, and Mexico. That scale, plus a fanbase speaking dozens of languages and arriving with wildly different mobility, sensory, and dietary needs, is exactly the kind of complexity a rules-based app struggles with: a static map can't reason about *your* situation. FIFA's own tournament app already offers AR wayfinding arrows to a seat or exit. What it can't do is hold a conversation — understand "I use a wheelchair and my train leaves in 40 minutes, what's my best move?" in whatever language the fan thinks in, and reason across accessibility needs, live conditions, and time pressure at once. That reasoning gap is where FanPath sits.

## Chosen vertical

**Fans → Navigation + Multilingual Assistance + Accessibility**, demonstrated for MetLife Stadium (East Rutherford, NJ — host of the July 19 Final).

Accessibility is one of the challenge's optional focus areas, but it's also one of the evaluation criteria — so rather than bolt it on, this submission treats it as load-bearing: every retrieval call accepts accessibility needs as a first-class filter (see `gather_facts` in `app/assistant.py`), not a caveat added to a generic answer.

## How it works

```
 fan message ──▶ sanitize (app/security.py)
                     │
                     ▼
           classify intent (app/assistant.py)
              keyword router, no LLM call
                     │
                     ▼
        retrieve facts (app/knowledge_base.py)
     deterministic JSON lookup — gate, amenity,
     walking time, live-congestion, filtered by
     the fan's stated accessibility needs
                     │
                     ▼
        build guarded prompt (app/security.py)
     facts + user message wrapped in explicit
     delimiters, system instructions kept separate
                     │
                     ▼
         stream from Gemini (app/gemini_client.py)
     reasons over the facts, replies in the fan's
     language, in 2-4 plain sentences
                     │
                     ▼
     SSE to browser (app/main.py) ──▶ rendered with
                                       textContent only
```

The split is deliberate: **Python decides what's true, Gemini decides how to say it.** Gate locations and walking times are dictionary lookups, not model guesses — faster, cheaper, and independently testable. The model's job is exactly what LLMs are good at: personalized, multilingual, context-aware phrasing over facts it's given, not facts it invents. The system instruction explicitly tells it to say so when the facts don't cover a question, rather than fill the gap.

## Try it

```bash
git clone https://github.com/YOUR_USERNAME/fanpath.git
cd fanpath
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then paste in a free key from https://aistudio.google.com/app/apikey
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Run the checks before you submit:

```bash
ruff check . && ruff format --check .
pytest -v
```

**On verification:** the core logic (`security.py`'s injection filter, `knowledge_base.py`'s lookups, `assistant.py`'s routing) was exercised directly against real inputs during development and behaved as documented below. The full `pytest` suite formalizes those same checks plus API-layer tests, but do run it yourself, along with one live smoke test against a real Gemini key, before you submit — this repo has exactly one submission attempt and no CI run replaces trying it in a browser.

## Sample interactions

| Fan says | Accessibility flags | What happens |
|---|---|---|
| "Where's the nearest restroom?" | wheelchair | Routes past a non-accessible restroom at the fan's own gate to the nearest one that isn't, and says why. |
| "¿Hay comida halal cerca?" | — | Retrieves the one halal-tagged stall in the dataset, replies in Spanish. |
| "Is Gate E busy right now?" | — | Reports simulated live congestion and suggests the least-congested alternative. |

## Mapping to the evaluation rubric

**Code quality (High impact).** Google Python Style Guide throughout: Google-style docstrings with Args/Returns/Raises, type hints on every public function, snake_case/PascalCase conventions, `ruff` enforcing both lint and formatting so style is never a matter of opinion. Each module has one job — `security.py` never touches the network, `knowledge_base.py` never imports the model client, route handlers in `main.py` stay thin. Commit history is small, single-purpose changes rather than one large drop.

**Problem statement alignment (High impact).** See "The problem" and "Chosen vertical" above — grounded in the tournament's real scale, deliberately positioned against what FIFA's own app already does, and built around one persona rather than a shallow pass at all eight focus areas.

**Security (Medium impact).** Two layers, both described in `app/security.py`:
- *App-level:* `GEMINI_API_KEY` is read from the environment only (`app/config.py`), never hardcoded; `.env` is git-ignored with `.env.example` committed instead; a fixed-window rate limiter (`app/main.py`) bounds API spend and abuse per client.
- *GenAI-level:* user text is treated as data, never instructions — the same mental model Google applies to indirect prompt injection against Gemini. `sanitize_user_input` detects override attempts (tested against both real attack phrasing and ordinary questions that merely mention "instructions," to keep false positives at zero); `build_guarded_prompt` wraps untrusted content in explicit delimiters with a reinforcement reminder; `sanitize_model_output` escapes model text server-side as a second, independent layer behind the frontend's `textContent`-only rendering. CI runs Google's OSV-Scanner against every dependency on each push.

**Efficiency (Medium impact).** Replies stream token-by-token rather than waiting for a full completion. Deterministic facts (gate locations, walking times) are answered by a dictionary lookup, not a model call — the LLM is invoked once per turn, not once per fact. The `google-genai` SDK already retries transient errors internally before raising, so `app/gemini_client.py` deliberately keeps its own outer retry small (2 attempts, randomized exponential backoff) rather than stacking a large retry budget on top of one the SDK already ran — per Google SRE guidance, more retries past that point mostly just adds worst-case latency for a fan waiting on an answer, not reliability. A hard timeout keeps a stalled request from hanging the turn indefinitely.

**Testing (Low impact).** Sized the way *Software Engineering at Google* describes: mostly small tests (`test_security.py`, `test_knowledge_base.py` — pure logic, no I/O) with a thin layer of medium tests (`test_api.py` — boots the real FastAPI app, but with `GeminiClient` swapped for an in-memory fake, so nothing hits the network). No end-to-end tests against the live API — they'd be slow, flaky, and burn real quota for marginal signal over the medium tests. CI runs the full suite on every push.

**Accessibility (Low impact).** Semantic HTML landmarks, a skip link, full keyboard navigability with visible focus rings, WCAG AA-target contrast, and `lang`/`dir` attributes that switch with the selected reply language (Arabic gets `dir="rtl"`, not just translated text). A "sensory-friendly mode" toggle is wired to a real behavior change (kills animation, softens the accent color), not just a label. A voice-input option (Web Speech API) is feature-detected and hidden entirely on browsers without support, so it's a bonus, never a dependency. Run Lighthouse yourself once the app is up — target 90+, but also do one manual keyboard-only pass, since automated audits catch only a fraction of real accessibility issues.

## Assumptions

- **Venue data is illustrative**, not sourced from MetLife Stadium or FIFA — `app/data/venue_metlife.json` says so directly, and a real deployment would point `knowledge_base.py` at an actual facilities/IoT feed instead of a JSON file.
- **Gate congestion is simulated**, standing in for what would be live turnstile or crowd-sensor telemetry.
- **One venue, one dataset** for demo scope — the architecture (zones → amenities → walking times) generalizes to any venue by swapping the JSON file; nothing in `assistant.py` or `main.py` is MetLife-specific.
- **Rate limiting is in-memory and single-process** — correct for a demo, and explicitly documented in `main.py` as something a multi-instance deployment would move to a shared store.
- **Translation is handled entirely by Gemini**, not a hand-rolled dictionary — deliberate, since language fluency is precisely what an LLM is for for this task.

## What's out of scope (by design, not oversight)

Real-time GPS/indoor positioning, live ticketing integration, and push notifications would all extend this naturally, but each pulls in infrastructure (venue partnerships, device permissions, a production data pipeline) that doesn't fit a single-attempt hackathon submission — better to make one reasoning loop genuinely solid than five integrations shallow.

## License

MIT — see [LICENSE](LICENSE).
