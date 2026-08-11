import { useState } from "react";

import { createBook, getStyles, searchGutendex } from "../../api/client";
import { StyleSwatch } from "../../components/StyleSwatch";
import { ErrorNotice, useAsync } from "../../components/common";
import type { CreateBookBody, DensityPreset, GutendexResult } from "../../api/types";
import { navigate } from "../../routes";

type SourceMode = "gutenberg" | "paste" | "upload";

const DENSITIES: { value: DensityPreset; label: string }[] = [
  { value: "lavish", label: "Most pictures" },
  { value: "classic", label: "Balanced (recommended)" },
  { value: "sparse", label: "Fewest pictures" },
];

// New Book wizard (§11.3): source → metadata/era → style → density → portraits → create. Rendered
// as one ordered, dense form (a workbench, not a modal stepper); Create posts to /api/admin/books.
export function NewBookWizard() {
  const styles = useAsync(() => getStyles(), []);
  // Consistency-friendly styles first (schema note on styles.json / DESIGN §9).
  const styleList = (styles.data?.styles ?? [])
    .slice()
    .sort((a, b) => Number(b.consistency_friendly) - Number(a.consistency_friendly));

  const [mode, setMode] = useState<SourceMode>("gutenberg");
  const [kind, setKind] = useState<"text" | "markdown">("markdown");
  const [text, setText] = useState("");
  const [filename, setFilename] = useState<string | null>(null);
  const [gutenbergId, setGutenbergId] = useState<number | null>(null);
  const [gutenbergPick, setGutenbergPick] = useState<GutendexResult | null>(null);

  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [era, setEra] = useState("");

  const [styleId, setStyleId] = useState<string | null>(null);
  const [density, setDensity] = useState<DensityPreset>("classic");
  const [imagesPerScene, setImagesPerScene] = useState(1);
  const [portraits, setPortraits] = useState(true);
  const [portraitReview, setPortraitReview] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<unknown>(null);

  const effectiveStyle = styleId ?? styleList[0]?.id ?? null;

  const sourceReady =
    (mode === "gutenberg" && gutenbergId !== null) ||
    ((mode === "paste" || mode === "upload") && text.trim().length > 0);
  const canCreate = sourceReady && !!effectiveStyle && !submitting;

  async function onUpload(file: File) {
    const content = await file.text();
    setText(content);
    setFilename(file.name);
    setKind(file.name.toLowerCase().endsWith(".md") ? "markdown" : "text");
  }

  async function onCreate() {
    if (!effectiveStyle) return;
    setSubmitting(true);
    setSubmitError(null);
    const source: CreateBookBody["source"] =
      mode === "gutenberg"
        ? {
            kind: "gutenberg",
            gutenberg_id: gutenbergId,
            title: (gutenbergPick?.title ?? title) || null,
            author: (gutenbergPick?.authors?.[0] ?? author) || null,
          }
        : {
            kind,
            text,
            filename: filename ?? (kind === "markdown" ? "pasted.md" : "pasted.txt"),
            title: title || null,
            author: author || null,
          };
    const body: CreateBookBody = {
      source,
      bake: {
        style_id: effectiveStyle,
        density_preset: density,
        images_per_scene: imagesPerScene,
        era: era || null,
        portraits_enabled: portraits,
        portrait_review: portraits && portraitReview,
        title: title || null,
        author: author || null,
      },
    };
    try {
      const res = await createBook(body);
      navigate({ name: "detail", id: res.book_id });
    } catch (err) {
      setSubmitError(err);
      setSubmitting(false);
    }
  }

  return (
    <section>
      <div className="crumbs">
        <a onClick={() => navigate({ name: "list" })}>Books</a> › New book
      </div>
      <h2>New book</h2>

      {/* 1. Choose a book */}
      <div className="wizard-step">
        <h3>1 · Choose a book</h3>
        <div className="row">
          <label>
            <input
              type="radio"
              name="mode"
              checked={mode === "gutenberg"}
              onChange={() => setMode("gutenberg")}
            />
            Search free classic books
          </label>
          <label>
            <input
              type="radio"
              name="mode"
              checked={mode === "paste"}
              onChange={() => setMode("paste")}
            />
            Paste the text myself
          </label>
          <label>
            <input
              type="radio"
              name="mode"
              checked={mode === "upload"}
              onChange={() => setMode("upload")}
            />
            Upload a file
          </label>
        </div>

        {mode === "gutenberg" && (
          <GutendexSearch
            picked={gutenbergPick}
            onPick={(r) => {
              setGutenbergPick(r);
              setGutenbergId(r.id);
              if (r.title) setTitle(r.title);
              if (r.authors[0]) setAuthor(r.authors[0]);
            }}
          />
        )}

        {(mode === "paste" || mode === "upload") && (
          <div style={{ marginTop: 8 }}>
            {mode === "upload" && (
              <div className="row" style={{ marginBottom: 6 }}>
                <input
                  type="file"
                  accept=".txt,.md,text/plain,text/markdown"
                  onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
                />
                {filename && <span className="muted mono">{filename}</span>}
              </div>
            )}
            <div className="row" style={{ marginBottom: 6 }}>
              <label>
                This text is:
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as "text" | "markdown")}
                >
                  <option value="markdown">Formatted (chapters marked with #)</option>
                  <option value="text">Plain text</option>
                </select>
              </label>
              <span className="muted">
                Not sure? Leave it on “Formatted” — it picks up chapter titles automatically.
              </span>
            </div>
            <textarea
              rows={8}
              aria-label="source text"
              placeholder="Paste the book text here…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
        )}
      </div>

      {/* 2. About the book */}
      <div className="wizard-step">
        <h3>2 · About the book</h3>
        <div className="row">
          <label>
            Title
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="filled in automatically"
            />
          </label>
          <label>
            Author
            <input
              type="text"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
            />
          </label>
          <label>
            Time &amp; place
            <input
              type="text"
              value={era}
              onChange={(e) => setEra(e.target.value)}
              placeholder="e.g. Victorian London"
            />
          </label>
        </div>
        <p className="muted" style={{ marginTop: 4 }}>
          Title and author fill in on their own for searched books. “Time &amp; place” is when and
          where the story happens, so the pictures match — leave it blank and we’ll guess.
        </p>
      </div>

      {/* 3. Pick an art style */}
      <div className="wizard-step">
        <h3>3 · Pick an art style</h3>
        <ErrorNotice error={styles.error} prefix="Could not load styles" />
        <p className="muted" style={{ marginTop: 0 }}>
          These little tiles are stand-ins, not real samples yet — pick by name for now.
        </p>
        <div className="style-grid">
          {styleList.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`style-tile${effectiveStyle === s.id ? " selected" : ""}`}
              onClick={() => setStyleId(s.id)}
              aria-pressed={effectiveStyle === s.id}
            >
              <StyleSwatch id={s.id} />
              <div className="name">{s.name}</div>
              <div className="muted" style={{ fontSize: 11 }}>
                {s.consistency_friendly
                  ? "keeps characters looking the same"
                  : "characters may look different picture to picture"}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 4. How many pictures */}
      <div className="wizard-step">
        <h3>4 · How many pictures</h3>
        <div className="row">
          {DENSITIES.map((d) => (
            <label key={d.value}>
              <input
                type="radio"
                name="density"
                checked={density === d.value}
                onChange={() => setDensity(d.value)}
              />
              {d.label}
            </label>
          ))}
        </div>
      </div>

      {/* 5. Illustration richness */}
      <div className="wizard-step">
        <h3>5 · How richly illustrated</h3>
        <div className="row">
          <label>
            <input
              type="number"
              min={1}
              max={9}
              value={imagesPerScene}
              onChange={(e) =>
                setImagesPerScene(Math.max(1, Math.floor(Number(e.target.value) || 1)))
              }
              style={{ width: 64 }}
            />
          </label>
          <span className="muted">
            Higher = more pictures, spaced evenly through the whole book. 1 = the density preset's
            default.
          </span>
        </div>
      </div>

      {/* 6. Character portraits */}
      <div className="wizard-step">
        <h3>6 · Character portraits</h3>
        <label>
          <input
            type="checkbox"
            checked={portraits}
            onChange={(e) => setPortraits(e.target.checked)}
          />
          Draw a portrait of each main character
        </label>
        {portraits && (
          <label className="wizard-suboption">
            <input
              type="checkbox"
              checked={portraitReview}
              onChange={(e) => setPortraitReview(e.target.checked)}
            />
            Pause and let me review the portraits before drawing the rest of the book
          </label>
        )}
      </div>

      <ErrorNotice error={submitError} prefix="Could not start the book" />

      <div className="row">
        <button className="primary" disabled={!canCreate} onClick={onCreate}>
          {submitting ? "Starting…" : "Make this book"}
        </button>
        <button onClick={() => navigate({ name: "list" })}>Cancel</button>
        {!sourceReady && <span className="muted">Pick a book first.</span>}
      </div>
    </section>
  );
}

function GutendexSearch({
  picked,
  onPick,
}: {
  picked: GutendexResult | null;
  onPick: (r: GutendexResult) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GutendexResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setResults(await searchGutendex(q));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ marginTop: 8 }}>
      <form className="row" onSubmit={run}>
        <input
          type="search"
          aria-label="book search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Type a book title, e.g. Dracula"
          style={{ minWidth: 260 }}
        />
        <button type="submit" disabled={loading || !q.trim()}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>
      <ErrorNotice error={error} prefix="Book search failed" />
      {results && results.length === 0 && <p className="muted">No matches — try a different title.</p>}
      {results && results.length > 0 && (
        <table style={{ marginTop: 6 }}>
          <tbody>
            {results.map((r) => (
              <tr
                key={r.id ?? r.title ?? Math.random()}
                className="clickable"
                onClick={() => onPick(r)}
              >
                <td style={{ width: 24 }}>
                  <input type="radio" name="gutenberg-pick" checked={picked?.id === r.id} readOnly />
                </td>
                <td>
                  {r.title}
                  <div className="muted" style={{ fontSize: 12 }}>
                    {r.authors.join(", ") || "unknown author"}
                    {!r.download_url && " · can’t be used (no text version available)"}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
