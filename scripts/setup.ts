// npm run setup
// Creates the TrueForge agent from agent/ (or updates it if it exists), and checks the server and the model.
// run-evals calls the same sync before every run, so the agent that runs always matches agent/ at HEAD.

import { client, die, env, headSha, readAgent, syncAgent } from "./lib.ts";

const tf = client();
const { agent, skills } = readAgent();

try {
  const { data: models } = await tf.models.list();
  const names = models.map((m) => m.name);
  if (!names.includes(agent.model.name)) {
    console.warn(
      `! Model "${agent.model.name}" is not configured on ${env.baseUrl}.\n` +
        `  Configured: ${names.join(", ") || "(none)"}\n` +
        `  Add a provider in Settings → Models, then set the model in agent/agent.json or TF_MODEL in .env.`,
    );
  }
} catch (e) {
  die(`Can't reach TrueForge at ${env.baseUrl}. Is it running? (npx @truefoundry/trueforge@latest)\n  ${(e as Error).message}`);
}

const saved = await syncAgent(tf, headSha());
console.log(`✓ Agent "${saved.name}" (${saved.id}) is in sync with agent/ at ${headSha().slice(0, 7)}`);
console.log(`  model: ${saved.manifest.model.name}`);
console.log(`  skills: ${skills.map((s) => s.name).join(", ") || "(none)"} — mode: ${agent.skill_mode ?? "inline"}`);
console.log(`  Try it in the UI: ${env.baseUrl} → Agents → ${saved.name} → Try`);
