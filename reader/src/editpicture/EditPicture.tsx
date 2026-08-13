import { useEffect, useMemo, useState } from "react";

import type { Storage } from "../shell";
import {
  candidateUrl,
  commitEdit,
  fetchEditContext,
  generateCandidate,
  type EditContext,
  type GenerateBody,
} from "../shelf";

// Post-publish "Edit picture" screen (ADR-0033/0034), reached from the plate lightbox. It mirrors
// the imagegen dev harness: the prompt that made the picture is pre-filled, the current image is the
// img2img starting point, and every generation knob the service exposes is available — Style, Model,
// Quality, Negative prompt, Seed, Change amount, and a character-likeness reference — with the whole
// form defaulted to the STYLE AND MODEL of the reader in view, so a comic-set page edits as comic.
//
// This component performs NO network I/O itself — every call goes through shelf/editPicture.ts (the
// ESLint fence forbids fetch outside shelf/+sync/). It is online-only; Reader mounts it only when the
// bakery is reachable. On commit the shelf downloads the private overlay so the change shows offline.

const CUSTOM_STYLE_ID = "custom";
const QUALITIES = ["fast", "standard", "high"] as const;
const SERVICE_DEFAULT_MODEL = ""; // sentinel option: let the service use its configured checkpoint

/** Read a picked image File into a bare base64 string (no data-URL prefix) for the JSON body. */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.onload = () => {
      const result = String(reader.result);
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

export function EditPicture({
  user,
  book,
  plateId,
  setId,
  storage,
  currentSrc,
  onDone,
}: {
  user: string;
  book: string;
  plateId: string;
  /** The set (reader) currently in view — "default" for the base book, or a "set-…" id. */
  setId: string;
  storage: Storage;
  /** The image currently shown for this plate (a local object URL) — the img2img starting image. */
  currentSrc: string;
  /** Close the editor; `changed` is true iff a replacement was committed (Reader re-reads the overlay). */
  onDone: (changed: boolean) => void;
}) {
  const [ctx, setCtx] = useState<EditContext | null>(null);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [caption, setCaption] = useState("");
  const [denoise, setDenoise] = useState(0.45);
  const [seedText, setSeedText] = useState("");
  const [styleId, setStyleId] = useState(CUSTOM_STYLE_ID);
  const [customStyle, setCustomStyle] = useState("");
  const [model, setModel] = useState(SERVICE_DEFAULT_MODEL);
  const [quality, setQuality] = useState<string>("standard");
  const [keepLikeness, setKeepLikeness] = useState(true);
  const [refImage, setRefImage] = useState<string | null>(null); // uploaded reference (base64)
  const [strengthOverride, setStrengthOverride] = useState(false);
  const [refStrength, setRefStrength] = useState(0.6);
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const c = await fetchEditContext(user, book, plateId, setId);
        if (!live) return;
        setCtx(c);
        setPrompt(c.prompt);
        setNegative(c.negative);
        setCaption(c.caption);
        setDenoise(c.denoise_default);
        setSeedText(c.seed == null ? "" : String(c.seed));
        setStyleId(c.style_id);
        setCustomStyle(c.custom_style ?? "");
        setModel(c.model ?? SERVICE_DEFAULT_MODEL);
        setQuality(c.quality_default);
        setKeepLikeness(c.has_cast_reference);
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [user, book, plateId, setId]);

  // The model dropdown always offers the reader's own checkpoint even if the service list is stale.
  const modelOptions = useMemo(() => {
    const list = ctx?.models ?? [];
    const current = ctx?.model ?? null;
    return current && !list.includes(current) ? [current, ...list] : list;
  }, [ctx]);

  const usingReference = keepLikeness || refImage != null;

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const seed = seedText.trim() === "" ? null : Number(seedText);
      const body: GenerateBody = {
        prompt,
        negative,
        seed,
        denoise,
        set_id: setId,
        style_id: styleId,
        custom_style: styleId === CUSTOM_STYLE_ID ? customStyle : null,
        model: model === SERVICE_DEFAULT_MODEL ? null : model,
        quality,
        use_cast_reference: keepLikeness,
        reference: refImage,
        reference_strength: usingReference && strengthOverride ? refStrength : null,
      };
      const cand = await generateCandidate(user, book, plateId, body);
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

  const onPickReference = (file: File | undefined) => {
    if (!file) {
      setRefImage(null);
      return;
    }
    void (async () => {
      try {
        setRefImage(await fileToBase64(file));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
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
            <span>Negative prompt</span>
            <textarea value={negative} onChange={(e) => setNegative(e.target.value)} rows={2} />
          </label>

          <label className="editpic-field">
            <span>Style</span>
            <select value={styleId} onChange={(e) => setStyleId(e.target.value)}>
              {ctx.styles.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
              <option value={CUSTOM_STYLE_ID}>Custom (free text)…</option>
            </select>
          </label>

          {styleId === CUSTOM_STYLE_ID && (
            <label className="editpic-field">
              <span>Custom style</span>
              <input
                type="text"
                value={customStyle}
                onChange={(e) => setCustomStyle(e.target.value)}
                placeholder="e.g. 35mm Tri-X 400, watercolour…"
              />
            </label>
          )}

          <label className="editpic-field">
            <span>Model</span>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              <option value={SERVICE_DEFAULT_MODEL}>(service default)</option>
              {modelOptions.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>

          <label className="editpic-field">
            <span>Quality</span>
            <select value={quality} onChange={(e) => setQuality(e.target.value)}>
              {QUALITIES.map((q) => (
                <option key={q} value={q}>
                  {q}
                </option>
              ))}
            </select>
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

          <fieldset className="editpic-field editpic-reference">
            <legend>Character likeness</legend>
            {ctx.has_cast_reference && (
              <label className="editpic-check">
                <input
                  type="checkbox"
                  checked={keepLikeness}
                  onChange={(e) => setKeepLikeness(e.target.checked)}
                />
                <span>Keep the character&rsquo;s face (from the cast portrait)</span>
              </label>
            )}
            <label className="editpic-subfield">
              <span>Reference photo (optional override)</span>
              <input
                type="file"
                accept="image/*"
                onChange={(e) => onPickReference(e.target.files?.[0])}
              />
            </label>
            {refImage && (
              <button type="button" className="editpic-linkbtn" onClick={() => onPickReference(undefined)}>
                remove reference photo
              </button>
            )}
            {usingReference && (
              <>
                <label className="editpic-check">
                  <input
                    type="checkbox"
                    checked={strengthOverride}
                    onChange={(e) => setStrengthOverride(e.target.checked)}
                  />
                  <span>Set likeness strength (else automatic)</span>
                </label>
                {strengthOverride && (
                  <label className="editpic-subfield">
                    <span>Likeness strength: {refStrength.toFixed(2)}</span>
                    <input
                      type="range"
                      min={0.2}
                      max={1}
                      step={0.05}
                      value={refStrength}
                      onChange={(e) => setRefStrength(Number(e.target.value))}
                    />
                  </label>
                )}
              </>
            )}
          </fieldset>

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
