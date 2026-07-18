// Generates src/generated/messages.ts from the server's AsyncAPI 3.0 schema.
// Usage: node scripts/generate-types.mjs [schema-url-or-path]
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const source = process.argv[2] ?? "http://localhost:8000/asyncapi.json";
const outDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "../src/generated",
);

async function loadSpec() {
  if (source.startsWith("http")) {
    const res = await fetch(source);
    if (!res.ok) throw new Error(`Failed to fetch ${source}: ${res.status}`);
    return res.json();
  }
  return JSON.parse(await readFile(source, "utf8"));
}

const spec = await loadSpec();

// Rewrite AsyncAPI component refs to standard JSON Schema $defs refs, and
// close object schemas so the generated types don't get index signatures.
function fix(schema) {
  if (Array.isArray(schema)) return schema.map(fix);
  if (schema === null || typeof schema !== "object") return schema;
  const out = {};
  for (const [key, value] of Object.entries(schema)) {
    out[key] =
      key === "$ref" && typeof value === "string"
        ? value.replace("#/components/schemas/", "#/$defs/")
        : fix(value);
  }
  if (
    out.type === "object" &&
    out.properties &&
    out.additionalProperties === undefined
  ) {
    out.additionalProperties = false;
  }
  // Pydantic marks `action` as optional (it has a default), but it is the
  // discriminator — make it required so TS can narrow the union on it.
  if (out.type === "object" && out.properties?.action) {
    out.required = [...new Set([...(out.required ?? []), "action"])];
  }
  return out;
}

// A chanx message entry points at its payload schema: {payload: {$ref: ...}}
const schemaName = (messageKey) => {
  const ref = spec.components.messages[messageKey]?.payload?.$ref;
  if (!ref) throw new Error(`No payload $ref for message ${messageKey}`);
  return ref.split("/").pop();
};

const messageKey = (ref) => ref.split("/").pop();

// Client -> server messages are the "receive" operations' inputs;
// server -> client messages are their replies.
const clientNames = new Set();
const serverNames = new Set();
for (const op of Object.values(spec.operations)) {
  if (op.action !== "receive") continue;
  for (const m of op.messages ?? [])
    clientNames.add(schemaName(messageKey(m.$ref)));
  for (const m of op.reply?.messages ?? [])
    serverNames.add(schemaName(messageKey(m.$ref)));
}

const $defs = fix(spec.components.schemas);
const allNames = [...new Set([...clientNames, ...serverNames])].sort();

const root = {
  title: "AgentMessage",
  oneOf: allNames.map((name) => ({ $ref: `#/$defs/${name}` })),
  $defs,
};

const banner = `/* eslint-disable */
/**
 * Generated from the server's AsyncAPI schema (${source}).
 * Do not edit by hand — run \`npm run generate\` instead.
 */`;

let ts = await compile(root, "AgentMessage", {
  bannerComment: banner,
  unreachableDefinitions: true,
  additionalProperties: false,
});

ts += `
export type ClientMessage = ${[...clientNames].sort().join(" | ")};
export type ServerMessage = ${[...serverNames].sort().join(" | ")};
export type ServerAction = ServerMessage["action"];
`;

await mkdir(outDir, { recursive: true });
await writeFile(join(outDir, "messages.ts"), ts);
console.log(
  `Wrote src/generated/messages.ts (${allNames.length} message types)`,
);
