// npm run configure-model
//
// Registers OpenAI-compatible providers on the local TrueForge server from the
// keys already in backend/.env (Hugging Face router → OpenRouter fallback), so
// no manual Settings → Models step is needed. Idempotent: safe to re-run.
//
// Model keys never enter this repo: they go straight from backend/.env into
// the TrueForge server config, which stores them redacted.

import { existsSync } from "node:fs";
import { join } from "node:path";
import { client, die, ROOT } from "./lib.ts";

// lib.ts already loaded .env from the repo root; also pull backend/.env.
if (existsSync(join(ROOT, "backend", ".env"))) process.loadEnvFile(join(ROOT, "backend", ".env"));

const tf = client();

interface Provider {
  name: string;
  type: "custom";
  baseUrl: string;
  apiKey: string | undefined;
  models: { name: string; modelId: string; contextLength?: number }[];
}

const providers: Provider[] = [
  {
    name: "truefoundry",
    type: "custom",
    // Stranger Builds managed AI Gateway — PAT + credits from the organisers.
    // Registered as "custom": the gateway is OpenAI-compatible; the dedicated
    // "truefoundry" provider type speaks a different protocol and rejects it.
    baseUrl: "https://stranger-builds.truefoundry.cloud/api/llm",
    apiKey: process.env.TRUEFORGE_TOKEN,
    models: [
      // Verified working through TrueForge (2026-11-05). Several gateway models
      // (gpt-oss-120b, deepseek, kimi-k3, qwen, minimax, glm) upstream as raw
      // NDJSON chunks, which TrueForge can't parse — register only these.
      // kimi-k2.7-code is open weights: the open-model story on sponsor credits.
      { name: "kimi-k27-code", modelId: "tfy-managed/kimi-k2.7-code", contextLength: 262144 },
      { name: "claude-sonnet-5-5", modelId: "tfy-managed/claude-sonnet-5-5", contextLength: 200000 },
      { name: "claude-haiku-4-5", modelId: "tfy-managed/claude-haiku-4-5-20251001", contextLength: 200000 },
    ],
  },
  {
    name: "huggingface",
    type: "custom",
    baseUrl: "https://router.huggingface.co/v1",
    apiKey: process.env.LLM_API_KEY,
    models: [{ name: "gemma-3-27b-it", modelId: "google/gemma-3-27b-it", contextLength: 131072 }],
  },
  {
    name: "openrouter",
    type: "custom",
    baseUrl: "https://openrouter.ai/api/v1",
    apiKey: process.env.LLM_FALLBACK_API_KEY,
    models: [
      { name: "gemma-3-27b-it-free", modelId: "google/gemma-3-27b-it:free", contextLength: 131072 },
      { name: "gemma-4-31b-it-free", modelId: "google/gemma-4-31b-it:free", contextLength: 262144 },
    ],
  },
];

let created = 0;
for (const p of providers) {
  if (!p.apiKey || p.apiKey.startsWith("<")) {
    console.log(`- skip ${p.name}: no API key in backend/.env or .env`);
    continue;
  }
  await tf.settings.modelProviders.createOrUpdate({
    manifest: {
      type: p.type,
      name: p.name,
      baseUrl: p.baseUrl,
      auth: { apiKey: p.apiKey },
      models: p.models.map((m) => ({
        name: m.name,
        modelId: m.modelId,
        properties: m.contextLength ? { contextLength: m.contextLength } : {},
      })),
    },
  });
  console.log(`✓ provider "${p.name}" → ${p.baseUrl} (${p.models.map((m) => `${p.name}/${m.name}`).join(", ")})`);
  created++;
}

if (!created) die("No providers configured — put an LLM_API_KEY or LLM_FALLBACK_API_KEY in backend/.env (or .env).");

const { data: models } = await tf.models.list();
console.log(`\nConfigured models on ${process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790"}:`);
for (const m of models) console.log(`  ${m.name}`);
console.log(`\nSet the agent's model in agent/agent.json (currently custom/...) to one of these, or set TF_MODEL in .env.`);
