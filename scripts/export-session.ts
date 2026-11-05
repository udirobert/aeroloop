// npm run export-session -- <session_id> [out.json]
// Saves a TrueForge session (the session, its turns and every turn's events) as JSON.
// run-evals and improve call this for you; use it by hand for any other session (e.g. one you ran in the UI).

import { client, die, exportSession, writeJson } from "./lib.ts";

const [sessionId, out] = process.argv.slice(2);
if (!sessionId) die("usage: npm run export-session -- <session_id> [out.json]");

const exp = await exportSession(client(), sessionId);
if (out) {
  writeJson(out, exp);
  console.log(`✓ ${exp.turns.length} turns → ${out}`);
} else {
  console.log(JSON.stringify(exp, null, 2));
}
