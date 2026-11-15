# Submission form — copy/paste answers

Form: https://www.openserv.ai/hackathon-2 (submission closes 2026-11-15 23:59 UTC)

**Track:** Open

**Project name:** AeroLoop

**Public repository:** https://github.com/udirobert/aeroloop

**Demo link or video:** https://github.com/udirobert/aeroloop/blob/main/docs/aeroloop-openserv-demo.mp4

**X post link:** _(paste the URL of the posted main tweet from `x-post.md`)_

**Short write-up:**

AeroLoop is an independent auditor for air-quality data. It corrects a cheap,
drifting PM2.5 source (the CAMS model) against a real reference monitor — LAQN
North Kensington, 192 ratified hourly readings — and proves every correction on a
chronological holdout it never tuned on. Rejected corrections are kept in the audit
trail as `vN-rejected` ghosts, never deleted.

SERV Reasoning is the correction engine, not a wrapper. Two SERV tiers (serv-nano,
serv-ultra) enter every tournament against non-SERV baselines with byte-identical
prompts and the same holdout windows; each proposal must beat the incumbent's
whole-holdout MAE and win a strict majority of three chronological sub-windows
before it ships. Every call's response id, finish_reason, token usage and cost are
persisted and shown in the dashboard.

What we measured: holdout MAE fell 23.269 → 20.234 µg/m³ (13.0%) over two accepted
corrections. serv-nano matched or beat the incumbent at $0.0007–0.0016 per run,
while serv-ultra cost 15–21× more for no accuracy gain — and twice refused the
benign prompt outright (finish_reason=content_filter, still billed). We did not
disable the filter; we record the refusal. An auditor that hides its own tool's
failures is not an auditor.

First market: UK construction/demolition dust monitoring, where Section 61 consents
already require continuous PM10 monitoring and the developer pays; the revised EU
Ambient Air Quality Directive (2024/2881) adds numeric uncertainty limits from
12 Dec 2026. Full write-up, evidence JSON and limitations: SUBMISSION-OPENSERV.md.