// Generate TypeScript type declarations from the JSON Schemas.
//
// Deterministic by construction: schemas are processed in sorted order and the
// banner carries no timestamp, so running this twice yields no diff (BUILD-PLAN
// S1 acceptance). Output: shared/types/<kind>.d.ts + index.d.ts, committed.
//
// Paths are resolved relative to THIS file, so it works from any cwd (repo root
// for the determinism check, or reader/ and admin-ui/ prebuild hooks).

import { readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemasDir = join(here, "schemas");
const outDir = join(here, "types");

const BANNER =
  "/* eslint-disable */\n" +
  "/**\n" +
  " * This file was automatically generated from a JSON Schema in shared/schemas.\n" +
  " * DO NOT EDIT IT BY HAND. Instead, edit the schema and run `node shared/gen-types.mjs`.\n" +
  " */";

const OPTIONS = {
  bannerComment: BANNER,
  additionalProperties: false,
  style: { singleQuote: false, semi: true },
  format: true,
  enableConstEnums: false,
  declareExternallyReferenced: true,
};

const pascalCase = (kind) =>
  kind
    .split(/[-_]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join("");

const files = (await readdir(schemasDir))
  .filter((f) => f.endsWith(".schema.json"))
  .sort();

const kinds = [];
for (const file of files) {
  const kind = file.replace(/\.schema\.json$/, "");
  kinds.push(kind);
  const schema = JSON.parse(await readFile(join(schemasDir, file), "utf-8"));
  const ts = await compile(schema, pascalCase(kind), OPTIONS);
  await writeFile(join(outDir, `${kind}.d.ts`), ts, "utf-8");
}

const index =
  BANNER +
  "\n\n" +
  kinds.map((k) => `export * from "./${k}";`).join("\n") +
  "\n";
await writeFile(join(outDir, "index.d.ts"), index, "utf-8");

console.log(`Generated ${kinds.length} type files: ${kinds.join(", ")}`);
