# Testing and Continuous Integration (Phase 5E)

## Test suites

All tests run without Ollama: they use a fake embedding model and a fake LLM, so they are fast (about 20 to 30 seconds for the API suite) and give the same result every time. The tests that need the real models are the evaluation run and the load test (see [evaluation.md](evaluation.md)).

| File | Covers |
|---|---|
| `tests/test_health.py` | The API starts and answers `/health` |
| `tests/test_eval_set.py` | The question set is complete and consistent with the intents, routes, tools and SOPs |
| `tests/test_rag.py` | Chunking, hybrid search, citations, the no-answer rule, classifier, PII, `/chat` end to end |
| `tests/test_tools.py` | Function calling, YES/NO confirmation, tickets, escalation, audit log, webhooks |
| `tests/test_phase4_api.py` | Roles, conversations, agent replies, ticket updates, human takeover, metrics, KB endpoints |
| `tests/test_auth.py` | Login tokens, lockout, `/chat` identity, webhook secret |
| `tests/test_reset.py` | Password reset link: single use, expiry, password rules, lock lifted, outbox |
| `tests/test_guardrails.py` | Injection filter (26 attacks, 23 normal messages), PII types, output filter, rate limits |
| `tests/test_memory.py` | Follow-up detection, history limits, attacks kept out of history, both escalation rules |
| `tests/test_eval_tools.py` | The scoring code, the eval files, the red-team set |
| `frontend/tests/test_app.py` | The Streamlit screens for each role, login, reset page, errors (backend replaced by a fake) |

Run them inside Docker:

```
docker compose exec api python -m pytest tests -q
docker compose exec frontend python -m pytest tests -q
docker compose exec api python -m pytest tests/test_auth.py -q    # one file
docker compose exec api python -m pytest tests -q -k lockout      # tests with a word in the name
```

About 215 API tests and 16 frontend tests at the end of Phase 5 (a parametrized test counts once per case).

## CI pipeline (`.github/workflows/ci.yml`)

GitHub Actions runs on every push to `main` or `master`, on every pull request, and on demand ("Run workflow" button).

| Job | Steps |
|---|---|
| **backend** | Install `requirements.txt` on Python 3.11 (the Docker version), run `pytest tests`, run the guardrail suite (`app.eval.run_eval --suite guardrails`, which exits with an error if any attack gets through or any normal message is blocked), and keep `data/eval/latest.md` as a downloadable artifact |
| **frontend** | Install `frontend/requirements.txt`, run `pytest tests` inside `frontend/` |

Dependencies are cached between runs. The two jobs run in parallel and a failure in either one marks the commit as failed.

**Not in CI, on purpose:** the full evaluation (113 questions and 17 scenarios) and the load test. They need the local language model and take many minutes, so they are run by hand before a release or a defense, and the report is saved with the documentation.

## Docker build check

`docker compose up --build` is the build test: the API image installs the same `requirements.txt` that CI uses, so a missing or broken dependency shows up in both places.

## Configuration notes

- `tests/pytest.ini` silences the pytest-asyncio loop-scope warning and turns off the `.pytest_cache` folder, so nothing extra appears in the mounted `tests/` folder.
- The test suite sets its own values for secrets and thresholds (`monkeypatch`), so a local `.env` does not change test results. `SECRET_KEY` in the CI file is only used for the test run.
- `.gitignore` keeps `.env`, `data/*` (databases, search index, evaluation reports), caches and delivery zips out of the repository. Only `data/.gitkeep` is tracked.

## Before a release or the defense

1. `docker compose exec api python -m pytest tests -q` and the frontend suite pass.
2. `docker compose exec api python -m app.eval.run_eval --judge` and read `data/eval/latest.md`.
3. `docker compose exec api python -m app.eval.load_test` and read `data/eval/load-latest.md`.
4. Copy both reports into `docs/` with the date and model name.
5. Push, and check that the CI run is green.
