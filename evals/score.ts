// The scorer. Deterministic: same reply in, same number out. Higher is better.
// Don't change it (or evals/tasks/) after run 1: every run must be scored the same way.
//
//   npm run score -- runs/run-01     re-score a saved run from its results.json
//   npm run score -- --selftest      check the scorer on perfect, empty and noisy answers
//
// Per task:  score = max(0, 1 - abs_err / 8)   → 0..1
//   abs_err = |predicted pm25 - expected_pm25| in µg/m³
// A task "passes" when abs_err <= PASS_ERR (2.0 µg/m³ — about one noise sigma).
// Run score = 100 × the mean task score → 0..100.

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ERR_SCALE = 8; // µg/m³ of absolute error that zeroes a task's score
export const PASS_ERR = 2.0; // µg/m³ — monitor noise is ~±3, so within 2 is a hit

export interface ScoredTask {
  id: string;
  title: string;
  holdout?: boolean;
  station_id: string;
  features: Record<string, number>;
  expected_pm25: number;
}
export interface TaskScore {
  task_id: string;
  holdout: boolean;
  score: number; // 0..1
  passed: boolean;
  parsed: boolean;
  predicted: number | null;
  expected: number;
  abs_err: number | null;
  direction: "low" | "high" | "exact" | null; // predicted vs expected
}

/** The estimate from the agent's reply: the last ```json block with a numeric pm25, or bare JSON. */
export function parsePrediction(reply: string): number | null {
  const blocks = [...reply.matchAll(/```json\s*\n([\s\S]*?)```/g)].map((m) => m[1]);
  const candidates = blocks.length ? [blocks[blocks.length - 1]] : [reply];
  for (const c of candidates) {
    try {
      const obj = JSON.parse(c.trim());
      const v = Number(obj?.pm25);
      if (Number.isFinite(v)) return v;
      return null;
    } catch {
      return null;
    }
  }
  return null;
}

export function scoreTask(task: ScoredTask, reply: string): TaskScore {
  const predicted = parsePrediction(reply);
  const base = { task_id: task.id, holdout: !!task.holdout, expected: task.expected_pm25 };
  if (predicted === null) {
    return { ...base, score: 0, passed: false, parsed: false, predicted: null, abs_err: null, direction: null };
  }
  const absErr = Math.abs(predicted - task.expected_pm25);
  return {
    ...base,
    score: round(Math.max(0, 1 - absErr / ERR_SCALE), 4),
    passed: absErr <= PASS_ERR,
    parsed: true,
    predicted,
    abs_err: round(absErr, 4),
    direction: absErr < 0.05 ? "exact" : predicted < task.expected_pm25 ? "low" : "high",
  };
}

export function scoreRun(tasks: TaskScore[]): { score: number; tasks_passed: number; tasks_total: number } {
  const mean = tasks.length ? tasks.reduce((s, t) => s + t.score, 0) / tasks.length : 0;
  return { score: round(100 * mean, 2), tasks_passed: tasks.filter((t) => t.passed).length, tasks_total: tasks.length };
}

function round(x: number, d: number): number {
  const k = 10 ** d;
  return Math.round(x * k) / k;
}

// ---------- CLI ----------

const here = dirname(fileURLToPath(import.meta.url));

function loadTasks(): ScoredTask[] {
  const dir = join(here, "tasks");
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(readFileSync(join(dir, f), "utf8")));
}

function reply(pm25: number): string {
  return "Estimate ready.\n\n```json\n" + JSON.stringify({ pm25 }) + "\n```\n";
}

function selftest(): void {
  const tasks = loadTasks();
  const perfect = tasks.map((t) => scoreTask(t, reply(t.expected_pm25)));
  const modelOnly = tasks.map((t) => scoreTask(t, reply(t.features.pm25_model)));
  const garbage = tasks.map((t) => scoreTask(t, "no idea"));
  const check = (name: string, got: number, want: number) => {
    const ok = got === want;
    console.log(`${ok ? "ok  " : "FAIL"} ${name}: ${got}${ok ? "" : ` (want ${want})`}`);
    if (!ok) process.exitCode = 1;
  };
  check("perfect answers score", scoreRun(perfect).score, 100);
  check("perfect answers pass", scoreRun(perfect).tasks_passed, tasks.length);
  check("unparseable answers score", scoreRun(garbage).score, 0);
  console.log(`info  parroting pm25_model scores: ${scoreRun(modelOnly).score} (the run-1 baseline the agent should beat)`);
}

function rescore(dir: string): void {
  const results = JSON.parse(readFileSync(join(resolve(dir), "results.json"), "utf8")) as { task_id: string; reply: string }[];
  const tasks = new Map(loadTasks().map((t) => [t.id, t]));
  const scored = results.map((r) => {
    const t = tasks.get(r.task_id);
    if (!t) throw new Error(`unknown task ${r.task_id}`);
    return scoreTask(t, r.reply);
  });
  for (const s of scored)
    console.log(
      `${s.passed ? "pass" : "    "} ${s.task_id.padEnd(32)} ${s.score.toFixed(2)}  predicted ${s.predicted} vs ${s.expected} (${s.direction ?? "unparsed"})`,
    );
  console.log(JSON.stringify(scoreRun(scored)));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const arg = process.argv[2];
  if (arg === "--selftest") selftest();
  else if (arg) rescore(arg);
  else console.log("usage: npm run score -- runs/run-NN | --selftest");
}
