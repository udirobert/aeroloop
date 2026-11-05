# TrueForge feedback note (draft — for the submission's required half-page)

**What we built:** a PM2.5-forecasting agent that reviews its own runs and
rewrites its own strategy skill, verified over 10 TrueForge sessions and two
independent learning arcs (63.91 → 87.03 on hosted Gemma, then 63.91 → 80.78
on Kimi K2.7 served through the organisers' managed AI Gateway).

## What worked well

- The agent-files-as-source-of-truth model (`agent/` synced via `agents.update`)
  made the whole loop auditable — every run pins the exact commit that ran.
- `skill_mode: "git"` end-to-end on macOS works: the local sandbox needed no
  extra packages, the agent reads its own `SKILL.md` from the cloned repo at
  the pinned commit (`sandbox.created` + `tool.response` events confirm it).
  The starter marked this TODO(verify) — happy to report it works.
- `sessions.createTurnStream` + `previousTurnId: "none"` is a clean way to run
  independent eval tasks in one session. Session export via
  `sessions.get/listTurns/listTurnEvents` covers the audit trail.

## What bit us (the actual bug)

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
