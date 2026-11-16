# Verify a prediction

Every prediction is **committed when it is saved**. At save time the
backend builds a canonical JSON payload (sorted keys, no spaces) containing the
station, timestamp, predicted value, strategy, inputs and a `committed_at`
UTC stamp, and stores its SHA-256 as `commit_hash` plus the exact payload
string. `GET /commitments/prediction/{id}` re-hashes the stored payload and
reports `hash_matches`, the reading that arrived later, and
`reading_recorded_after_commit` (reading `recorded_at` > `committed_at`).

`committed_at` is **self-reported** by the AeroLoop server — by itself it
proves nothing. What is publicly provable is *"this exact prediction existed
by `<anchor time>`"*: once the day's Merkle root is confirmed on Base, the
block timestamp (`existed_by`) is a third-party bound, and once the
OpenTimestamps receipt upgrades, the Bitcoin block is another. A verifier
then compares that bound with when the truth became public — LAQN ratified
readings are published days later, so **daily anchoring is sufficient for
ratified-truth audits, but cannot prove a same-day forecast**.
`target_after_existed_by` reports whether the prediction's target timestamp
postdates the anchor bound (i.e. it provably predated the hour it predicts).

Each `kind` says what the commitment means:

- `live` — predicted in real time, truth not yet published: the real claim.
- `simulated` — `/demo-day` offline pairs; labelled, never presented as live.
- `hindcast` — backfilled over already-ratified truth; the commitment records
  *when* the row was written, not a pre-truth guarantee.
- `uncommitted` — legacy rows predating commitments (hash fields NULL).

Daily, all un-anchored commits are folded into a Merkle tree —
`aeroloop-merkle-v1`: `leaf = sha256(0x00‖hash)`, `node = sha256(0x01‖left‖right)`,
last node duplicated on odd levels, leaves ordered by prediction id. The batch
record lands in `anchors/<date>.json` — the **published record**. The verify
endpoint rebuilds the proof from that file (not from mutable DB rows),
recomputes its root, and reports `published_root` plus `roots_consistent`
(published root == DB anchor root).

The root is anchored twice:

- **Bitcoin (OpenTimestamps).** `anchors/<date>.root` holds the 32 raw root
  bytes and is stamped with `ots stamp`; verify with
  `ots verify anchors/<date>.root.ots`. OTS commits to `sha256` of that file,
  i.e. to `sha256(root_bytes)`.
- **Base.** A self-send transaction carries calldata `"AEROLOOP1" + root` —
  check it on the explorer (`basescan.org` / `sepolia.basescan.org`) linked
  from `GET /anchors`. Base Sepolia by default; see `.env.example`.
