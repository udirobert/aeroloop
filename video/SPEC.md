# SPEC — "Run 11" (AeroLoop, Stranger Builds submission)

GOAL:   the judge believes this agent genuinely improves itself — because they
        watched it fail, diagnose, and repair without a human touching it.
OUTPUT: HyperFrames, 1920×1080, 30fps → docs/stranger-builds-video.mp4
TIME:   84 s × 30 = 2520 frames. VO drives every cut (vo-alignment.json).

LOOK:   the medium is a machine session log.
        ground   #0e1216 deep ink, 2.5% grain (grain-overlay comp), faint
                 horizontal rules at 3% opacity every 8px (ledger lines)
        ink      #e6ede8
        accent   #57e6c9 phosphor cyan — scores, ticks, caret, wisp line
        fail     #ff5b4d — run 11, OVERFIT stamp, the ×1.20 strike; nowhere else
        dim      #5a6a66 labels/hairlines
        display  Inter 900, tabular nums for scores (96–240px, tracking -3%)
        mono     JetBrains Mono 400/700 (labels 20–26px, code 26–34px)
        no shadows beyond one 0 24px 60px rgba(0,0,0,.45) on cards;
        light = none (it's a log, not a stage)

OBJECTS: score readout (huge tabular digits, decimal), run tick rows (8/24),
         SKILL.md card (mono, looks like the real file), task grid
         (4 stations × 6 chips, holdout = outlined), terminal card (mono,
         $ prompt, cyan caret), commit hash chips, red OVERFIT stamp
         (rotated 4°, bordered, letterspaced), AeroLoop wordmark + wisp line.

MOTION: enters = power3.out 0.35s from y+18; stamps = power4.in 0.22s scale
        1.6→1 + 2-frame settle; digit rolls = baked frame rows (toFixed(2))
        over 1.2s sine.inOut; nothing breathes, nothing drifts; every cut on
        a VO clause boundary; camera = none except 6% push on screenshots.

SHOTS (host data-start → duration, scene id):
  0.0  s01-hook      10.0s  87.03 cyan "run 04 · evals/tasks"; 10 ticks sweep;
                            at ~7.0s digits roll down to 55.1 → red, label
                            swaps to "run 11 · evals/hard"; OVERFIT stamp 9.0s.
                            Hands off: red digits hold into cut.
 10.0  s02-system    14.4s  ghost-film.mp4 (muted, real scene) → dashboard
                            screenshot push → report panel crop; mono labels
                            "forecasts PM2.5 / scores vs monitors / rewrites
                            its own playbook" land on VO clauses.
 24.4  s03-rule      10.0s  SKILL.md card "estimate = pm25_model × 1.20" types;
                            run rows 1–4 scores climb 63.91 → 87.03, 8 ticks.
 34.4  s04-break     10.4s  24-chip grid lights cold; readout flips 87.03→55.1
                            red (echo of s01); ×1.20 card strikes through;
                            stamp "OVERFIT" at ~42s.
 44.8  s05-learn     15.6s  terminal card: "$ trueforge improve --tasks-dir
                            evals/hard" types; lines print (19 failed tasks →
                            commit a2fcc71); diff card: −"× 1.20" collapses,
                            +station uplifts / +NO2 term / +wind rule expand;
                            small line: guard rejected a memorizing edit.
 60.4  s06-recovery   5.6s  digits roll 55.1 → 63.65 cyan; 24-grid refills
                            12/24 lit; small "run 13 · 61.77 · kept".
 66.0  s07-proof      9.2s  terminal: git clone @ pinned commit → sandbox.
                            created → cat SKILL.md; line "the playbook it
                            edits is cloned from the repo it ships in".
 75.2  s08-endcard    8.8s  wisp line draws → "AeroLoop" wordmark →
                            github.com/udirobert/aeroloop +
                            "Stranger Builds · TrueForge challenge".

AUDIO:  assets/vo.mp3 (VO, start 0); assets/music.wav (bed, start 0, -14dB
        under VO). Hit baked into bed at 34.6s and 9.0s; lift at 60.6s.
CAPTIONS: one captions track (root), mono 26px, bottom-center 80% title-safe,
        lines timed to vo-alignment.json clause starts.

BANNED: defaults (dark void + small floaters — avoided via ledger rules +
        grain + full-bleed cards), glow/bloom, purple-blue gradients, glass
        cards, three-card rows, KPI grid, docked logo, "Introducing", floating
        particles; plus: no fake UI — every screen is a real screenshot or
        real repo text; no decimals rounded to integers on scores.

QA:     f0 hook readable; f~260 digits mid-roll; f~1050 grid lit + stamp;
        f~1650 diff expanded; f~1950 63.65 landed; f~2300 wordmark + URL;
        captions inside title-safe; red appears only on failure beats.
