import { useEffect, useState } from "react";

import type { Storage } from "../shell";
import {
  candidateUrl,
  commitEdit,
  fetchEditContext,
  generateCandidate,
  type EditContext,
} from "../shelf";

// Post-publish "Edit picture" screen (ADR-0033), reached from the plate lightbox. It resembles the
// imagegen harness: the prompt that made the picture is pre-filled, the current image is the img2img
// starting point, and the user generates alternatives (a "change amount"/denoise slider) until happy,
// then replaces the picture and its caption — privately, for this profile only.
//
// This component performs NO network I/O itself — every call goes through shelf/editPicture.ts (the
// ESLint fence forbids fetch outside shelf/+sync/). It is online-only; Reader mounts it only when the
// bakery is reachable. On commit the shelf downloads the private overlay so the change shows offline.

export function EditPicture({
  user,
  book,
  plateId,
  storage,
  currentSrc,
  onDone,
}: {
  user: string;
  book: string;
  plateId: string;
  storage: Storage;
  /** The image currently shown for this plate (a local object URL) — the img2img starting image. */
  currentSrc: string;
  /** Close the editor; `changed` is true iff a replacement was committed (Reader re-reads the overlay). */
  onDone: (changed: boolean) => void;
}) {
  const [ctx, setCtx] = useState<EditContext | null>(null);
  const [prompt, setPrompt] = useState("");
  const [caption, setCaption] = useState("");
  const [denoise, setDenoise] = useState(0.65);
  const [seedText, setSeedText] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const c = await fetchEditContext(user, book, plateId);
        if (!live) return;
        setCtx(c);
        setPrompt(c.prompt);
        setCaption(c.caption);
        setDenoise(c.denoise_default);
        setSeedText(c.seed == null ? "" : String(c.seed));
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [user, book, plateId]);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const seed = seedText.trim() === "" ? null : Number(seedText);
      const cand = await generateCandidate(user, book, plateId, { prompt, denoise, seed });
      setToken(cand.token);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(false);
    }
  };

  const replace = async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await commitEdit(storage, user, book, plateId, token, caption);
      onDone(true);
    } catch (e) {
      setError(friendlyError(e));
      setBusy(false);
    }
  };

  const previewSrc = token ? candidateUrl(user, book, plateId, token) : currentSrc;

  return (
    <div className="editpic" role="dialog" aria-modal="true" aria-label="Edit picture">
      <div className="editpic-bar">
        <button type="button" className="editpic-cancel" onClick={() => onDone(false)}>
          ← Cancel
        </button>
        <span className="editpic-title">Edit picture</span>
      </div>

      {error && <p className="editpic-error">{error}</p>}

      {!ctx ? (
        <p className="editpic-loading">Loading…</p>
      ) : (
        <div className="editpic-body">
          <div className="editpic-preview">
            <img
              className="editpic-img"
              src={previewSrc}
              alt={token ? "New candidate picture" : "Current picture (starting image)"}
            />
            {!token && <span className="editpic-badge">Starting image</span>}
          </div>

          <label className="editpic-field">
            <span>Prompt</span>
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} />
          </label>

          <label className="editpic-field">
            <span>Change amount: {denoise.toFixed(2)}</span>
            <input
              type="range"
              min={0.2}
              max={0.9}
              step={0.05}
              value={denoise}
              onChange={(e) => setDenoise(Number(e.target.value))}
            />
          </label>

          <label className="editpic-field">
            <span>Seed (blank = random)</span>
            <input
              type="text"
              inputMode="numeric"
              value={seedText}
              onChange={(e) => setSeedText(e.target.value)}
              placeholder="random"
            />
          </label>

          <label className="editpic-field">
            <span>Caption</span>
            <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={2} />
          </label>

          <div className="editpic-actions">
            <button type="button" disabled={busy || !prompt.trim()} onClick={() => void generate()}>
              {busy ? "Working…" : token ? "Regenerate" : "Generate"}
            </button>
            <button
              type="button"
              className="editpic-replace"
              disabled={busy || !token}
              onClick={() => void replace()}
            >
              Replace picture
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function friendlyError(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  // 503 from the candidate endpoint = the single GPU is busy (likely a bake in progress).
  if (/\b503\b/.test(msg)) {
    return "The picture engine is busy (a book may be baking). Try again in a moment.";
  }
  return msg;
}
