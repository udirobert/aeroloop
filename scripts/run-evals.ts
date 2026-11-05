// npm run run-evals [-- --no-commit] [-- --allow-dirty]
//
// One run = one TrueForge session. Each task in evals/tasks/ is one root turn in that session
// (so tasks don't see each other). Then:
//   runs/run-NN/results.json   the agent's reply and score for each task
//   runs/run-NN/score.json     the run score and per-task details
//   runs/run-NN/session.json   the whole session, exported from TrueForge
//   runs/summary.csv           one new row
// and a commit "run NN: score X" (skip with --no-commit).

import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { scoreRun, scoreTask } from "../evals/score.ts";
import {
  client,
  die,
  exportSession,
  flag,
  git,
  headSha,
  isClean,
  loadTasks,
  readAgent,
  runDir,
  runTurn,
  sessionStats,
  SUMMARY_CSV,
  syncAgent,
  taskPrompt,
  writeJson,
} from "./lib.ts";

const HEADER = "run,session_id,agent_commit,score,date_utc,tasks_passed,tasks_total,tokens,tool_calls,duration_s";

// 1. The agent and the eval must be committed, so agent_commit says exactly what ran.
if (!isClean("agent", "evals") && !flag("allow-dirty")) {
  die("agent/ or evals/ has uncommitted changes. Commit them first, so agent_commit points at what ran.");
}
const agentCommit = headSha() + (isClean("agent", "evals") ? "" : "-dirty");

if (!existsSync(SUMMARY_CSV) || readFileSync(SUMMARY_CSV, "utf8").trim() === "") writeFileSync(SUMMARY_CSV, HEADER + "\n");
const rows = readFileSync(SUMMARY_CSV, "utf8").trim().split("\n").slice(1).filter(Boolean);
const run = rows.length + 1;
const dir = runDir(run);
const nn = String(run).padStart(2, "0");

// 2. Make the TrueForge agent match agent/ at this commit.
const tf = client();
const agent = await syncAgent(tf, headSha());
const tasks = loadTasks();
console.log(`Run ${nn}: agent "${agent.name}" at ${agentCommit.slice(0, 7)}, ${tasks.length} tasks`);

// 3. One session for the whole run. https://trueforge.dev/api/overview#session
const started = Date.now();
const { data: session } = await tf.sessions.create({
  agent: { name: readAgent().agent.name },
  metadata: { purpose: "eval", run: nn, agent_commit: agentCommit },
});
await tf.sessions.update(session.id, { title: `eval run ${nn} @ ${agentCommit.slice(0, 7)}` });
console.log(`  session ${session.id}`);

// 4. Each task is one root turn; score the reply.
const results = [];
for (const task of tasks) {
  process.stdout.write(`  ${task.id.padEnd(32)} `);
  const turn = await runTurn(tf, session.id, taskPrompt(task));
  const scored = scoreTask(task, turn.text);
  results.push({ ...scored, turn_id: turn.turnId, status: turn.status, error: turn.error, reply: turn.text });
  const pred = scored.predicted === null ? "unparsed" : `${scored.predicted} vs ${scored.expected} (${scored.direction})`;
  console.log(`${turn.status === "done" ? "" : `[${turn.status}${turn.error ? `: ${turn.error}` : ""}] `}${scored.score.toFixed(2)}${scored.passed ? "  pass" : ""}  ${pred}`);
}
const durationS = Math.round((Date.now() - started) / 1000);
const total = scoreRun(results);

// 5. Save the run.
const exp = await exportSession(tf, session.id);
const stats = sessionStats(exp);
writeJson(join(dir, "results.json"), results);
writeJson(join(dir, "score.json"), { run, session_id: session.id, agent_commit: agentCommit, ...total, ...stats, duration_s: durationS });
writeJson(join(dir, "session.json"), exp);

const date = new Date().toISOString().replace(/\.\d+Z$/, "Z");
appendFileSync(
  SUMMARY_CSV,
  [run, session.id, agentCommit, total.score, date, total.tasks_passed, total.tasks_total, stats.tokens, stats.toolCalls, durationS].join(",") + "\n",
);

console.log(`\nRun ${nn} score: ${total.score} (${total.tasks_passed}/${total.tasks_total} tasks passed, ${stats.tokens} tokens)`);

// 6. Commit the run, so git history reads: run 1 → agent change → run N.
if (!flag("no-commit")) {
  git("add", "runs");
  git("commit", "-q", "-m", `run ${nn}: score ${total.score}`, "-m", `TrueForge session: ${session.id}\nagent_commit: ${agentCommit}`);
  console.log(`✓ Committed ${dir.replace(/.*\/runs\//, "runs/")}. Next: npm run improve`);
}
