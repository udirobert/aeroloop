# History — how AeroLoop got here

The hackathon-era record, kept for provenance. The current direction is
[`vision.md`](vision.md); these entries are preserved, not updated.

AeroLoop started as a Hacktoberfest 2026 "Ghost in the Machine" entry
(rejected strategies are kept as `vN-rejected` — the ghosts of ideas that
didn't work; see `ghost-over-london-plan.md` for the scene it produced), then
became a Stranger Builds / TrueForge entry. This file consolidates
`stranger-builds.md`, `trueforge-feedback-note.md` and `submission-blurb.md`.

## Submission blurb (as submitted)

> AeroLoop is an agent that gets measurably better every time it runs: it
> forecasts London PM2.5, scores itself against real ground monitors, and
> rewrites its own strategy skill between runs — in git.
> Across 13 real TrueForge sessions on two open-weight models it peaked at
> 87.03 — then, frozen against 24 unseen tasks, it scored 55.1, diagnosed its
> own overfitting, and rewrote its playbook to reach 63.65.
> Every run is a verifiable session pinned to a commit the agent wrote — the
> agent edits itself, not us.

## Run 1 vs run N (TrueForge)

*The same agent, rebuilt on TrueForge: a PM2.5-forecasting agent whose
estimation strategy lives in `agent/skills/pm25-strategy/SKILL.md`, which it
rewrites itself.*

* **Task and score:** estimate ground-level PM2.5 for 8 fixed London
  station/hour scenarios (`evals/tasks/`); score = 100 × mean(1 − |predicted −
  measured| / 8) per task (`runs/summary.csv`).
* **Run 1 → run 4:** 63.91 → 86.09 — peak 87.03 at run 2; all 8 tasks pass by
  run 4 (`runs/summary.csv`). Then, on a clean-room replay on the sponsor
  gateway, **run 6 → run 7:** 63.91 → 80.63.
* **The change that did it:** commit `8b8c1d1` — after run 1 the agent added a
  flat +3.0 µg/m³ correction to its strategy (`Agent-Session:
  01m6ptf9n9rmc2cn38kbbns1kb`).
* **What the agent learned:** the CAMS model systematically under-reads the
  ground monitors; after overshooting once (+3.0 → +2.0, an honest regression
  to 83.28) it learned a station-specific correction — +2.0 everywhere, +4.6
  at Marylebone. On the second arc a different model reached the same
  conclusion a different way: a ×1.20 uplift (`Agent-Session:
  01m6pw7n97x4g1k9mavc9k3frh`) — same lesson, different hypothesis.
* **What still fails:** nothing material on the task set — the residual error
  is irreducible monitor noise (~±3 µg/m³). Run 5 (55.94) carries one
  transient transport error, kept in the record rather than silently rerun.

Two independent learning arcs are in the record: runs 1–4 on
`huggingface/gemma-3-27b-it`, runs 5–8 on `truefoundry/kimi-k27-code`
(open weights served through the organisers' managed AI Gateway, on the
provided credits). Runs 9–10 switch `skill_mode` to `"git"`: the agent reads
its skill as a **real TrueForge skill** cloned from this repo at the pinned
commit through the local sandbox — the starter's `TODO(verify)` path,
verified end-to-end (see `runs/run-09/session.json`: `sandbox.created` and
skill-read tool calls).

**Generalization check — `evals/hard/` (runs 11–13):** the learned playbook
was then frozen against a 24-task suite it never saw (6/station, 4 holdout).
Its ×1.20 rule scored **55.1 → improved to 63.65** after one self-edit that
replaced the single multiplier with per-station uplifts plus an NO2 traffic
term — the honest finding being that the small-suite correction *didn't*
generalize, and the agent diagnosed that itself. Run 13 (61.77, one unparsed
reply) and a rejected self-edit (the overfit guard caught it quoting a task
value) are kept in the record too.

### Run it

```bash
npm install
npx @truefoundry/trueforge@latest   # keep running; serves http://localhost:8790
npm run configure-model             # registers providers from backend/.env keys
npm run setup && npm run run-evals  # baseline
npm run improve && npm run run-evals
```

The backend is untouched — this harness (`agent/`, `evals/`, `scripts/`,
`runs/`) sits alongside it and treats AeroLoop's recorded prediction/reading
pairs as the eval set. Ground truth remains the labelled synthetic stand-in;
the scorer is a deterministic port of `evaluation.py`'s error logic.

---

## Stranger Builds — eligibility assessment (archived)

Checked 2026-11-05 against strangerbuilds.com, the Luma event, and
github.com/nerdconf/trueforge-starter.

### The event

NERDCONF "Stranger Builds" Halloween hackathon — online, solo or team of 2,
~$10k in prizes/credits. Theme: build something new, ship it live, get real
users on it within the week.

| Date | Event |
|---|---|
| Fri 30 Oct 23:00 UTC | Build window opened |
| Sat 31 Oct | Kickoff (SF, Melbourne, Bangalore, online) |
| **Sun 8 Nov 23:59 ART** | **Submissions close** |
| 10–15 Nov | Judging |
| Thu 19 Nov | Results |

Flow: register on Luma → sign the pact → activate with the Duck on ASI:One
(Fetch.ai) → enter Duck World → pick a challenge at the Challenge Fair →
ship a public link → get feedback → submit. Last version submitted before
the close is what's judged.

### The TrueForge challenge

"Build an agent that gets better every time it runs" (sponsor: TrueForge by
TrueFoundry, `npx @truefoundry/trueforge@latest`). An agent on TrueForge that
reviews its own runs, rewrites its own instructions/skills, and scores higher
next run.

*(The full event-notes file is in git history; the sections below preserve the
two parts still worth reading.)*

## TrueForge feedback note (as drafted for the submission)

**What worked well**

- The agent-files-as-source-of-truth model (`agent/` synced via
  `agents.update`) made the whole loop auditable — every run pins the exact
  commit that ran.
- `skill_mode: "git"` end-to-end on macOS works: the local sandbox needed no
  extra packages, the agent reads its own `SKILL.md` from the cloned repo at
  the pinned commit (`sandbox.created` + `tool.response` events confirm it).
  The starter marked this TODO(verify) — it works.
- `sessions.createTurnStream` + `previousTurnId: "none"` is a clean way to
  run independent eval tasks in one session. Session export via
  `sessions.get/listTurns/listTurnEvents` covers the audit trail.

**What bit us**

- **Managed AI Gateway streaming incompatibility.** Registered as a `custom`
  provider against `https://stranger-builds.truefoundry.cloud/api/llm`, most
  upstreams (`tfy-managed/gpt-oss-120b`, `deepseek-*`, `qwen-*`, `minimax-*`,
  `glm-*`, `kimi-k3`) return raw newline-delimited `chat.completion.chunk`
  JSON objects instead of SSE `data:` frames. TrueForge fails the turn with
  `[Model Error] JSON parsing failed: Unexpected non-whitespace character
  after JSON`. Working models: `claude-*` and `kimi-k2.7-code`. Either the
  gateway should normalize upstreams to SSE, or TrueForge's custom-provider
  client should accept NDJSON.
- The dedicated `type: "truefoundry"` provider manifest rejects `name` and
  expects a different protocol than this gateway speaks — docs could clarify
  which gateway dialect it targets.
- A transient `write EPIPE` mid-run zeroed one task's score; a retry option in
  the turn API would keep eval runs honest without manual reruns.
- Minor: `settings.modelProviders` manifest model `name` rejects dots
  (`qwen3.8-max` → must be `qwen38-max`), easy to hit when mirroring upstream
  model ids.
