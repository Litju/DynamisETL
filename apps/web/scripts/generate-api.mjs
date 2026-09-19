#!/usr/bin/env node
// Keep the generated TypeScript API schema in lockstep with FastAPI OpenAPI.
//
//   node scripts/generate-api.mjs --write   regenerate src/api/schema.d.ts
//   node scripts/generate-api.mjs --check   fail when the file is stale (CI)
//
// The OpenAPI document itself is produced by `dynamis-openapi`; this script only
// converts it to TypeScript, so the Python side stays the single schema author.

import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const documentPath = join(here, "..", "src", "api", "openapi.json");
const outputPath = join(here, "..", "src", "api", "schema.d.ts");

async function generate() {
  const source = JSON.parse(await readFile(documentPath, "utf8"));
  const ast = await openapiTS(source);
  return astToString(ast);
}

const mode = process.argv.includes("--check") ? "check" : "write";
const generated = await generate();

if (mode === "check") {
  let existing = "";
  try {
    existing = await readFile(outputPath, "utf8");
  } catch {
    console.error("schema.d.ts is missing; run `pnpm api:generate`");
    process.exit(1);
  }
  if (existing !== generated) {
    console.error(
      "API schema drift: src/api/schema.d.ts does not match src/api/openapi.json. " +
        "Run `pnpm api:generate` and commit the result.",
    );
    process.exit(1);
  }
  console.log("API schema is in sync");
} else {
  await writeFile(outputPath, generated, "utf8");
  console.log(`wrote ${outputPath}`);
}
