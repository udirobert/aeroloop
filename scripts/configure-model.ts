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
  baseUrl: string;
  apiKey: string | undefined;
  models: { name: string; modelId: string; contextLength?: number }[];
}

const providers: Provider[] = [
  {
    name: "huggingface",
    baseUrl: "https://router.huggingface.co/v1",
    apiKey: process.env.LLM_API_KEY,
    models: [{ name: "gemma-3-27b-it", modelId: "google/gemma-3-27b-it", contextLength: 131072 }],
  },
  {
    name: "openrouter",
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
    console.log(`- skip ${p.name}: no API key in backend/.env`);
    continue;
  }
  await tf.settings.modelProviders.createOrUpdate({
    manifest: {
      type: "custom",
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
