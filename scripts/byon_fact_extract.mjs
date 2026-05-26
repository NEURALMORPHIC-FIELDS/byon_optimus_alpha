// Canonical FactExtractor bridge (CLI).
//
// Reuses the REAL BYON Optimus FactExtractor (external/.../scripts/lib/fact-extractor.mjs)
// — it is NOT reimplemented here. This wrapper only supplies the two transports the
// extractor needs: a minimal `anthropic` client (Node global fetch → Anthropic Messages
// API, so no @anthropic-ai/sdk install is required) and a `mem` function that POSTs to the
// canonical memory-service. Reads a JSON payload from stdin, prints the result as JSON.
//
//   echo '{"text":"...","role":"user","threadId":"u","channel":"web"}' | node scripts/byon_fact_extract.mjs
//
// Env: ANTHROPIC_API_KEY (required), BYON_MEMORY_SERVICE_URL (default :8000),
//      BYON_CLAUDE_MODEL (default claude-sonnet-4-6).

import { extractAndStoreFacts, classifyTrust } from
  "../external/byon_optimus/byon-orchestrator/scripts/lib/fact-extractor.mjs";

const MEM_URL = (process.env.BYON_MEMORY_SERVICE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const MODEL = process.env.BYON_CLAUDE_MODEL || "claude-sonnet-4-6";

const anthropic = {
  messages: {
    create: async ({ model, max_tokens, temperature, system, messages }) => {
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": process.env.ANTHROPIC_API_KEY || "",
          "anthropic-version": "2023-06-01",
          "content-type": "application/json",
        },
        body: JSON.stringify({ model, max_tokens, temperature, system, messages }),
      });
      if (!r.ok) throw new Error("anthropic " + r.status);
      return await r.json(); // { content: [{type:'text', text}], ... }
    },
  },
};

async function mem(payload) {
  const r = await fetch(MEM_URL + "/", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await r.json();
  return { body };
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString("utf-8");
}

(async () => {
  try {
    if (!process.env.ANTHROPIC_API_KEY) {
      console.log(JSON.stringify({ ok: false, canonical: false, reason: "no ANTHROPIC_API_KEY" }));
      return;
    }
    const payload = JSON.parse((await readStdin()) || "{}");
    const out = await extractAndStoreFacts({
      anthropic, model: MODEL, mem,
      text: payload.text || "",
      role: payload.role || "user",
      threadId: payload.threadId || payload.thread_id || null,
      channel: payload.channel || "web",
    });
    // per-fact trust tiers for the report (re-derive via the canonical classifier)
    const tiers = {};
    for (const f of out.facts || []) {
      const factText = `${f.subject} ${f.predicate.replace(/_/g, " ")} ${f.object}`;
      const t = classifyTrust({ factText, kind: f.kind, source: "extractor" }).trust;
      tiers[t] = (tiers[t] || 0) + 1;
    }
    console.log(JSON.stringify({
      ok: true, canonical: true,
      facts: out.facts || [], ctx_ids: out.ctxIds || [],
      trust_report: out.trustReport || [], trust_tiers: tiers,
    }));
  } catch (e) {
    console.log(JSON.stringify({ ok: false, canonical: false, reason: String(e && e.message || e) }));
  }
})();
