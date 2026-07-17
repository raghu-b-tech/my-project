# Agent context for FanPath

If you (an AI coding agent) are continuing work on this repository, follow
these standards on every change, not just when reminded.

## What this project is
FanPath is a GenAI navigation/accessibility/multilingual concierge for fans
at MetLife Stadium during FIFA World Cup 2026, built for the PromptWars
"Smart Stadiums & Tournament Operations" challenge. Full context in
`README.md`.

## Non-negotiables

1. **Never hardcode secrets.** `GEMINI_API_KEY` and every other config value
   come from `app/config.py`, which reads the environment. If you add a new
   setting, add it to `Settings`, `.env.example`, and `README.md` together.

2. **Keep the split.** `app/knowledge_base.py` answers deterministic
   "what/where" questions with plain Python - no LLM call. `app/assistant.py`
   is the only place that constructs a prompt and calls Gemini. Don't let
   routes in `app/main.py` call `GeminiClient` directly. Same logic applies
   to anything with zero FastAPI dependency, like `app/rate_limiter.py` -
   keep it that way so it stays testable without booting the app.

3. **User input is data, never instructions.** Any new code path that puts
   user-supplied text into a prompt must go through
   `security.sanitize_user_input` and `security.build_guarded_prompt`. Any
   new code path that renders model output must go through
   `security.sanitize_model_output`, and the frontend must keep using
   `textContent`, never `innerHTML`, for that output.

4. **Style.** Python follows the Google Python Style Guide: Google-style
   docstrings (Args/Returns/Raises), type hints on public functions,
   snake_case functions/variables, PascalCase classes. This is enforced,
   not just stated - `ruff`'s `select` list includes `D` (docstring
   presence/format), so a new public function with no docstring fails
   lint, it doesn't just look inconsistent later. Run `ruff format .` and
   `ruff check .` before committing - don't hand-format. `mypy app` runs
   in CI too (advisory for now - see README "Code quality" section for
   why); tighten your own types until it's clean rather than adding
   `# type: ignore`.

5. **Tests are small by default.** A new function in `knowledge_base.py`,
   `security.py`, or `assistant.py` gets a small test (no network, no
   FastAPI app, sub-millisecond) in the matching `tests/test_*.py` file.
   Only add to `tests/test_api.py` (medium: boots the app, still no real
   network - `GeminiClient` is monkeypatched) if you're testing routing or
   HTTP-layer behavior specifically. Don't add end-to-end tests that call
   the real Gemini API - they're slow, flaky, and cost real quota.

6. **Commits stay small and single-purpose.** One logical change per
   commit, imperative-mood summary line, body explains why. Don't bundle a
   refactor with a feature change.

7. **Repo size.** Stay under 10MB total. Never commit `node_modules/`,
   `.venv/`, model weights, or media files - `.gitignore` already excludes
   the obvious ones, but check `du -sh .git` before a big commit anyway.

8. **Single branch.** Work on `main`. Don't create feature branches for this
   submission - the hackathon rules require exactly one branch in the repo.

## Before you consider a change done
- [ ] `ruff check . && ruff format --check .` passes (this now includes
      docstring-presence checks - see rule 4)
- [ ] `mypy app` has no new findings you can't explain
- [ ] `pytest` passes
- [ ] If you touched `app/data/venue_metlife.json`, the change is still
      clearly demo/illustrative data, not presented as real venue data
- [ ] README updated if you changed setup steps, assumptions, or the
      chosen vertical
