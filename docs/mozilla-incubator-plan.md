# Mozilla Human-Scale AI Incubator — prep plan

Deadline for the short proposal: **Fri 20 Nov 2026, 23:59 PT** (Sat 21 Nov 07:59 UTC).
Prize: $300k for 12 months from April 2027, up to $500k / 3 years, non-dilutive.
Seven projects chosen worldwide; ~3 slots are pre-reserved anchor teams.
Call: https://www.mozillafoundation.org/en/what-we-do/grantmaking/incubator/human-scale-ai/call-for-proposals/

## What they're scoring

- **Working technology already deployed with the people it serves** (early pilot OK)
- **Early product-community fit** — returning users, external contributors,
  community shaping governance, partners piloting, downstream adoption
- **All three principles:** *Small* (small models, low compute), *Intentional*
  (user/community agency over data + governance), *Tailored* (fit-for-purpose)
- AI core to the solution + novel approach; charitable purpose; public-good
  deliverable (open source, datasets, methodology)

Current self-assessment: **6/10**. Strong on Small + Tailored + charitable
purpose. Weak on product-community fit (no users yet) and Intentional
(our data is public environmental data, not personal data — the agency story
must be reframed as "anyone can verify / anyone can propose").

## Moves, ranked by score impact

### 1. Partner outreach — today (highest leverage, needs lead time)
Email 3–5 people: a UK dust-monitoring consultancy, a council air-quality /
planning officer, Reppo + OpenServ contacts, Breathe London.
One question: "would an independent verification appendix be useful to you?"
One real reply converts the weakest form answer ("none of these yet") into
"partners collaborating". This is also Milestone 3's success metric anyway.

### 2. Public deployment — today/tomorrow
Deploy backend + dashboard + verify endpoint to a public URL reviewers can
click. "Deployed with the people it serves" can't be argued from localhost.
(Milestone 3 work pulled forward.)

### 3. Open the tournament publicly — tomorrow
Publish repo + a DEV post inviting external correction strategies. Three
checkboxes in one move: contributors, community-governance, downstream
adoption. This *is* the Intentional story: anyone can propose, anyone can
verify the anchors, rejected strategies stay in the record.

### 4. Second location: the Netherlands — **built 2026-11-16**
Breathe London key requested but out of our control; NL needed **zero keys**
and is already live in `data/aeroloop.db`:

- **Reference:** `sensors/luchtmeetnet.py` adapter + `--network luchtmeetnet`
  on `reference_sites.py`. Public API, no auth, fair-use rate limit
  (probe at `PROBE_CONCURRENCY=2`; >5-day windows 302-redirect to the iq host).
  Empirical qualification 1–9 Nov 2026: **74 PM2.5 / 86 PM10 qualifying sites
  of 103 probed**.
- **Sensors:** `sensor.community` `filter/country=NL` — **1,426 unique PM
  sensors** upserted (feed duplicates each sensor ~2×; count is unique uids).
  ~43× London's open-data density.
- **Co-location (≤500 m): 11 verified candidates for both PM2.5 and PM10**
  (nearest 7.3 m — sc:89661 next to NL49680 Almere). Evidence:
  `submission/evidence/colocation-nl-run1.json`.
- **Story bonus:** RIVM already publishes *corrected* citizen-sensor data via
  Samen Meten — auditing it is the same incumbent-calibration pattern as
  Breathe London's `ScaledValue`. And NL is the EU 2024/2881 second market:
  "two countries, two regulatory regimes, same referee."
- **First real sensor-vs-reference audit — done 2026-11-16.** `sensor_audit.py`
  pulled archive.sensor.community history for all 11 candidates (sub-hourly
  CSVs aggregated to UTC hourly means; P1→PM10, P2→PM2.5) and scored each
  against its RIVM reference over 1–9 Nov. All 11 produced valid scores
  (~154–169 paired h each, all 7 qualifying days, completeness 1.0). Honest
  mixed verdict — **PM2.5: 4 fit / 3 drifting / 4 unfit** (slope 0.52–1.91,
  bias −8.3 to +13.8 µg/m³, drift flag on 7 of 11). **PM10: 11/11 unfit** —
  driven by slope over-response (1.02–2.60, 9 of 11 above the 1.35 band); a
  real signal that matches the known low-cost-PM10 over-read, scored
  indicatively against the EPA PM2.5 yardstick (no dedicated PM10 band yet).
  Evidence: `sensor-trust-nl-run1.json` (PM2.5), `sensor-trust-nl-pm10-run1.json`.

Fallbacks if needed later: Defra UK-AIR SOS (open, no key — any UK city);
OpenAQ (free self-serve key, global coverage); PurpleAir (self-serve key).

### 5. Adaption Labs — timeboxed optional (one afternoon max)
What it is: Mozilla Ventures–backed platform — AutoScientist trains a custom
model you own on your task; Adaptive Data optimises datasets. We have a
Builder plan + 2,250 credits to Feb 2027.

The one useful move: train **one owned small correction model** on the
22,309-pair dataset and enter it in the tournament. Converts "we call other
people's models" into "we own a small task-specific model" — the literal
Human-Scale thesis — and attacks our open question (regime-aware correction
a constant slope can't fix). Mozilla Ventures lineage is a nice narrative
wink, not a reason to build on it.

Risks: unknown credit coverage, new platform, and our data is tabular
time-series — AutoScientist may be LLM-training-oriented. Timebox: SDK +
upload + start a run, or drop it.

### 6. Base mainnet anchor — before submission
Testnet → mainnet makes "publicly proven, checkable by anyone" literally
true. Small ETH cost, high reviewer credibility.

## Proposal framing (mapped to the actual form)

- **Technology:** the independent referee for air-quality AI — commit-before-
  truth hashes, chronological holdout, blind peer-evaluation gate, public
  anchors. Evidence: CAMS unfit at all 26 London reference sites on 22,309
  real hourly pairs — the product working as intended.
- **Small:** tournament measures whether small models (SERV Nano, Gemma,
  TabPFN, deterministic heuristic) match frontier models — a live public
  benchmark of "small is enough". Infra: laptop + SQLite + public data.
- **Intentional:** communities/planning officers currently must trust
  vendor-bundled calibration. AeroLoop hands them independent, checkable
  proof; the open tournament gives them agency over what counts as evidence.
- **Tailored:** built around the UK 190 µg/m³ construction dust action level
  and EU 2024/2881; reference sites qualified by probing data because LAQN
  metadata is wrong both ways; second country (NL) added for fit, not scale.
- **PCF signals:** honest answers — partners in discussion, open tournament
  launching. Do not oversell; honesty is the brand.

## Schedule

| Day | Work |
|---|---|
| Mon 16 | Outreach emails + NL API spike (adapter + co-location scan) + deploy starts |
| Tue 17 | Open-tournament DEV post + public deployment live + draft proposal |
| Wed 18 | Adaption run (or drop) + Base mainnet anchor + proposal v2 |
| Thu 19 | Polish + submit early — buffer before Fri-night deadline |

## What not to do

- Don't fabricate product-community fit — "none yet + real early signals" beats
  an inflated claim.
- Don't spend >half a day on Adaption while the proposal is unwritten.
- Don't lead with crypto/Reppo jargon — anchors are an implementation detail;
  the pitch is "independent proof for air quality".
- Keep NL honest: same referee, second country — not "scaling to Europe" hype.
