import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { HttpArtsetApi } from "./artsetApi";

// Phase 4 (ADR-0014): the reader's picture-set control client hits the right URL/verb and parses or
// raises ApiError. Kept in shelf/ so the ESLint network fence stays green. URLs/shapes only.

const USER = "kris";
const BOOK = "usr-abc123def456";
const SET = "set-0123456789ab";

function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  const spy = vi.fn((input: string | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init)),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("HttpArtsetApi", () => {
  it("fetchSetList GETs the list endpoint and parses it", async () => {
    const doc = { book_id: BOOK, user_id: USER, active_set_id: "default", sets: [] };
    const spy = stubFetch(() => new Response(JSON.stringify(doc), { status: 200 }));
    const out = await new HttpArtsetApi().fetchSetList(USER, BOOK);
    expect(out).toEqual(doc);
    expect(spy.mock.calls[0][0]).toBe(`/api/artsets/${USER}/${BOOK}`);
  });

  it("createSet POSTs the body as JSON", async () => {
    const made = { set_id: SET, status: "generating" };
    const spy = stubFetch(() => new Response(JSON.stringify(made), { status: 200 }));
    const out = await new HttpArtsetApi().createSet(USER, BOOK, { kind: "style", style_id: "engraving" });
    expect(out).toEqual(made);
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`/api/artsets/${USER}/${BOOK}`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ kind: "style", style_id: "engraving" });
  });

  it("deleteSet DELETEs the set endpoint", async () => {
    const spy = stubFetch(() => new Response("{}", { status: 200 }));
    await new HttpArtsetApi().deleteSet(USER, BOOK, SET);
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`/api/artsets/${USER}/${BOOK}/${SET}`);
    expect(init?.method).toBe("DELETE");
  });

  it("fetchStyles GETs the catalog and returns the styles array", async () => {
    const doc = { styles: [{ id: "engraving", name: "Victorian Engraving", consistency_friendly: true }] };
    stubFetch(() => new Response(JSON.stringify(doc), { status: 200 }));
    expect(await new HttpArtsetApi().fetchStyles()).toEqual(doc.styles);
  });

  it("raises ApiError with the status on a non-ok response", async () => {
    stubFetch(() => new Response("nope", { status: 404 }));
    await expect(new HttpArtsetApi().fetchSetList(USER, BOOK)).rejects.toMatchObject({
      constructor: ApiError,
      status: 404,
    });
  });
});
