import { useEffect, useMemo, useState } from "react";

import type { Cast } from "@scriptorium/shared";

import type { BundleReader } from "../readerview/BundleReader";
import { visibleCharacters } from "./filter";

// The dramatis-personae page (DESIGN §13): a full-screen overlay listing the book's MAJOR cast, each
// with a portrait thumb (if resident), name, and one-line. It is an overlay — NOT a page injected into
// the reading order — so positions/anchors and the byte-stable pagination are untouched. Characters are
// gated by the furthest-read spoiler filter (ADR-0008): a character first mentioned ahead of where the
// reader has reached does not appear. Portrait raw PNGs aren't downloaded; the reader-required derivative
// `images/thumbs/portraits/{slug}.webp` is, so we resolve that (falling back to a monogram disc).

export function CastPage({
  reader,
  cast,
  furthestSeq,
  onClose,
}: {
  reader: BundleReader;
  cast: Cast;
  furthestSeq: number;
  onClose: () => void;
}) {
  const characters = useMemo(
    () => visibleCharacters(cast, furthestSeq).filter((c) => c.major),
    [cast, furthestSeq],
  );
  const [portraits, setPortraits] = useState<Record<string, string | null>>({});

  useEffect(() => {
    let live = true;
    void Promise.all(
      characters.map(
        async (c) => [c.slug, await reader.imageUrl(`images/thumbs/portraits/${c.slug}.webp`)] as const,
      ),
    ).then((pairs) => {
      if (live) setPortraits(Object.fromEntries(pairs));
    });
    return () => {
      live = false;
    };
  }, [reader, characters]);

  return (
    <section className="cast-page" role="dialog" aria-label="Dramatis personae">
      <div className="cast-bar">
        <h2>Dramatis Personae</h2>
        <button type="button" onClick={onClose}>
          Done
        </button>
      </div>
      {characters.length === 0 ? (
        <p className="cast-empty">No one has been introduced yet.</p>
      ) : (
        <ul className="cast-list">
          {characters.map((c) => (
            <li key={c.slug} className="cast-entry" data-cast-slug={c.slug}>
              {portraits[c.slug] ? (
                <img className="cast-portrait" src={portraits[c.slug] ?? undefined} alt="" />
              ) : (
                <span className="cast-portrait cast-initial" aria-hidden="true">
                  {c.name.replace(/^the\s+/i, "").charAt(0).toUpperCase()}
                </span>
              )}
              <div className="cast-meta">
                <span className="cast-name">{c.name}</span>
                <span className="cast-oneline">{c.one_line}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
