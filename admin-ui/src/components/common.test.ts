import { describe, expect, it } from "vitest";

import { formatTimestamp } from "./common";

// Server timestamps are UTC; the workbench should render them in the operator's local time.

// Local rendering of a parsed instant, computed the same way the helper should — so the assertion
// holds in any timezone the test runner happens to use, while still proving LOCAL getters are used.
function expectedLocal(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

describe("formatTimestamp", () => {
  it("renders a UTC timestamp in local time, compact shape", () => {
    const iso = "2026-08-12T01:35:14+00:00";
    expect(formatTimestamp(iso)).toBe(expectedLocal(iso));
    expect(formatTimestamp(iso)).toMatch(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/);
  });

  it("treats an offset, a Z, and a naive value as the same UTC instant", () => {
    const z = formatTimestamp("2026-08-12T01:35:14Z");
    expect(formatTimestamp("2026-08-12T01:35:14+00:00")).toBe(z);
    expect(formatTimestamp("2026-08-12T01:35:14")).toBe(z); // naive → assumed UTC
  });

  it("returns empty for empty/nullish and the raw string for garbage", () => {
    expect(formatTimestamp("")).toBe("");
    expect(formatTimestamp(null)).toBe("");
    expect(formatTimestamp(undefined)).toBe("");
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });
});
