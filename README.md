# Session Doctor

**Find, prove and fix transaction-ownership bugs in FastAPI + async SQLAlchemy apps, then keep them out with a CI gate.**

Built solo for the IBM Bob 2.0 Hackathon (lablab.ai), with IBM Bob IDE as the fixing engine.

---

## The problem

FastAPI + async SQLAlchemy apps break the rule "one owner per transaction", and the resulting bugs are easy to write and hard to see:

- **Silent data loss.** On FastAPI ≥ 0.118, code after `yield` in a dependency runs *after the response is sent*. If `get_db` commits there, a failed commit still returns 201.
- **`MissingGreenlet` 500s** from expired attributes after commit, or lazy-loaded relationships in async code.
- **"A transaction is already begun"** from `db.begin()` after autobegin.
- **Partial writes** when helpers commit before validation finishes.
- **Leaked connections** from one session shared across `asyncio.gather` / `create_task`, or a module-level session that sits "idle in transaction" and blocks migrations.

Several of these never produce an error at the endpoint that causes them. That makes them hard to find by reading logs, and it's hard to know when you've fixed them all.

## What Session Doctor does

| Step | Who | What |
|---|---|---|
| 1. **Scan** | `session_doctor/` (deterministic, Python `ast`) | Builds a session-ownership graph (where each session is created, passed, committed, closed) and applies 8 rules → text / JSON report |
| 2. **Prove** | IBM Bob (custom mode + skill) | Reproduces each high finding's symptom before touching code |
| 3. **Fix** | IBM Bob | Refactors to the one-owner pattern; done only when the scanner reports 0 high findings and tests pass |
| 4. **Guard** | GitHub Action + Bob rules file | Scanner runs on every PR with no LLM and no Bobcoins. Bob's workspace rules keep new Bob-written code on the convention |

### Rules

| Rule | Name | Catches |
|---|---|---|
| SD001 | commit-after-yield | Commit in a `yield` dependency (runs after the response on FastAPI ≥ 0.118) |
| SD002 | helper-commits | A helper that receives a session and commits it |
| SD003 | read-after-commit | Attribute read after `commit()` with `expire_on_commit=True` (needs review) |
| SD004 | lazy-relationship | Relationship read in async code without an eager-load option for *that* relationship |
| SD005 | begin-after-autobegin | `session.begin()` after the session already autobegan |
| SD006 | shared-session-concurrency | One session passed to several coroutines in `asyncio.gather` |
| SD007 | unsafe-background-work | Request session handed to `create_task` / background work |
| SD008 | session-outlives-request | Module-level sessions, or sessions stored on long-lived objects |

## Results on the test fixture

`shopfront/` is a ~700-line FastAPI + async SQLAlchemy + Postgres storefront with **8 planted session bugs (B1–B8)** and **2 decoys** (correct code that looks suspicious). It was generated outside Bob so Bob's first look at it was the trial. The answer key and the 10 hidden end-to-end tests are in [`eval/`](eval/).

### Scanner (deterministic)

| Input | High findings | Bugs covered | Decoys flagged | Exit |
|---|---|---|---|---|
| Untouched fixture | 8 | **8/8** (one finding per bug) | 0/2 | 1 (CI fails) |
| Reference fix (`eval/reference_fix.diff`) | 0 | n/a | 0/2 | 0 (CI passes) |

Full report: [`docs/shopfront_report.txt`](docs/shopfront_report.txt) / [`docs/shopfront_report.json`](docs/shopfront_report.json). Rule unit tests: `33 passed`.

### Bob without vs. with Session Doctor

| Run | Prompt | Bugs fixed (hidden tests) | Decoys broken | Bobcoins |
|---|---|---|---|---|
| Baseline, round 1 | "This API has problems with how it uses database sessions. Find and fix them." | 5/8 (missed B1, B6, B8) | 0 | — |
| Baseline, round 2 (same conversation) | Explicitly asked to resolve the remaining DB issues | 7/8 (missed B6) | 0 | 8.08 total at time of check |
| **Session Doctor mode** | Scanner report + `session-doctor` skill | **TODO** | **TODO** | **TODO** |

Caveat: the baseline wasn't fully blind, because the Bob conversation had explored the code before the fix prompt.

**The takeaway:** Bob can fix these bugs when it's pointed at them. The hard parts are knowing they exist and knowing when you're done. Round 2 happened only because a human knew more bugs remained, and one still survived. Session Doctor supplies the work list and the stopping condition.

## How IBM Bob is used

- **Custom mode** [`.bob/custom_modes.yaml`](.bob/custom_modes.yaml): `🩺 Session Doctor`, which runs scan → prove → fix → verify.
- **Skill** [`.bob/skills/session-doctor/SKILL.md`](.bob/skills/session-doctor/SKILL.md): the playbook, with rule → symptom → correct fix. It includes the tempting wrong fix for SD001 (`async with db.begin()` around `yield`) and says not to use it.
- **Workspace rules** [`.bob/rules/session-ownership.md`](.bob/rules/session-ownership.md) so any Bob-generated DB code follows the convention.
- **`.bobignore`** excludes `eval/`, so Bob never sees the answer key during fix runs.
- Bob task session summaries: [`bob_sessions/`](bob_sessions/).

Deterministic code does the detection and the CI gate. Bob does the reasoning: reproducing, refactoring, and judging `needs_review` findings.

## Run it

Requires Python 3.10+ (no third-party dependencies for the scanner).

```bash
python -m session_doctor scan shopfront                    # text report, exit 1 on high findings
python -m session_doctor scan shopfront --format json --out report.json
python -m session_doctor scan shopfront --fail-on never    # report only
python -m pytest -q session_doctor/tests                   # rule unit tests
```

Hidden end-to-end tests (need Docker for Postgres): see [`eval/ANSWER_KEY.md`](eval/ANSWER_KEY.md). They wipe the `shopfront` tables on each run.

```bash
cd shopfront && docker compose up -d db && cd ..
pip install -r eval/tests_hidden/requirements.txt -r shopfront/requirements.txt
SHOPFRONT_DIR=$PWD/shopfront python -m pytest -v eval/tests_hidden
```

## CI gate

[`.github/workflows/session-doctor.yml`](.github/workflows/session-doctor.yml):

- **self-test** (every push) runs the rule unit tests, asserts the scanner finds exactly 8 high findings on the buggy fixture, and asserts it finds 0 on the reference fix.
- **gate** (pull requests) runs `session_doctor scan shopfront --fail-on high`. It blocks a PR that introduces a high-confidence session bug.

## Limitations

- Static analysis of common patterns only. It's not a general dataflow engine, and it tracks sessions across function calls and imports within the scanned tree.
- Tuned and evaluated on one fixture written for this project. Not yet run on real-world repos.
- Existing tools cover nearby ground. flake8-async and flake8-sqlalchemy2 check lines and files and model style; queryspy catches N+1 queries at runtime. Session Doctor's angle is modelling session *ownership* across functions.

## Repo layout

```
session_doctor/        scanner (loader → ownership graph → rules → report) + unit tests
shopfront/             buggy fixture app (8 planted bugs, 2 decoys)
eval/                  answer key, hidden e2e tests, reference fix (ignored by Bob)
.bob/                  Bob custom mode, skill, workspace rules
.github/workflows/     CI gate
docs/                  scanner reports
bob_sessions/          Bob task session summary screenshots
```
