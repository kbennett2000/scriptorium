import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

// Proves the zero-online-read fence actually fires (DESIGN §13): a `fetch()` outside src/shelf/ and
// src/sync/ is a lint error; the same call inside the boundary is allowed. If someone weakens the
// eslint.config.js rule, this test goes red.

const SNIPPET = `export function load() {\n  return fetch("/api/library");\n}\n`;

async function lintAt(filePath: string): Promise<ESLint.LintResult[]> {
  // cwd defaults to the process cwd (the reader package), so eslint.config.js is discovered.
  const eslint = new ESLint();
  return eslint.lintText(SNIPPET, { filePath });
}

function boundaryErrors(results: ESLint.LintResult[]): number {
  return results[0].messages.filter((m) => m.ruleId === "no-restricted-syntax").length;
}

describe("network-boundary ESLint rule", () => {
  it("flags fetch() outside shelf/ and sync/", async () => {
    const results = await lintAt("src/readerview/leak.ts");
    expect(boundaryErrors(results)).toBeGreaterThan(0);
  });

  it("allows fetch() inside shelf/", async () => {
    const results = await lintAt("src/shelf/ok.ts");
    expect(boundaryErrors(results)).toBe(0);
  });

  it("allows fetch() inside sync/", async () => {
    const results = await lintAt("src/sync/ok.ts");
    expect(boundaryErrors(results)).toBe(0);
  });
});
