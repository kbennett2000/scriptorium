import { useState } from "react";

import { createBook, getStyles, searchGutendex } from "../../api/client";
import { StyleSwatch } from "../../components/StyleSwatch";
import { ErrorNotice, useAsync } from "../../components/common";
import type { CreateBookBody, DensityPreset, GutendexResult } from "../../api/types";
import { navigate } from "../../routes";

type SourceMode = "gutenberg" | "paste" | "upload";

const DENSITIES: { value: DensityPreset; label: string }[] = [
  { value: "lavish", label: "Lavish — most plates" },
  { value: "classic", label: "Classic — balanced (default)" },
  { value: "sparse", label: "Sparse — fewest plates" },
];

// New Book wizard (§11.3): source → metadata/era → style → density → portraits → create. Rendered
// as one ordered, dense form (a workbench, not a modal stepper); Create posts to /api/admin/books.
export function NewBookWizard() {
  const styles = useAsync(() => getStyles(), []);
  // Consistency-friendly styles first (schema note on styles.json / DESIGN §9).
  const styleList = (styles.data?.styles ?? [])
    .slice()
    .sort((a, b) => Number(b.consistency_friendly) - Number(a.consistency_friendly));

  const [mode, setMode] = useState<SourceMode>("paste");
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
  const [portraits, setPortraits] = useState(true);

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
        era: era || null,
        portraits_enabled: portraits,
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
        <a onClick={() => navigate({ name: "list" })}>Books</a> › New Book
      </div>
      <h2>New Book</h2>

      {/* 1. Source */}
      <div className="wizard-step">
        <h3>1 · Source</h3>
        <div className="row">
          <label>
            <input
              type="radio"
              name="mode"
              checked={mode === "gutenberg"}
              onChange={() => setMode("gutenberg")}
            />
            Gutendex search
          </label>
          <label>
            <input
              type="radio"
              name="mode"
              checked={mode === "paste"}
              onChange={() => setMode("paste")}
            />
            Paste text
          </label>
          <label>
            <input
              type="radio"
              name="mode"
              checked={mode === "upload"}
              onChange={() => setMode("upload")}
            />
            Upload file
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
                Kind:
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as "text" | "markdown")}
                >
                  <option value="markdown">markdown</option>
                  <option value="text">text</option>
                </select>
              </label>
              <span className="muted">
                markdown honours front-matter + <code>#</code> chapter headings.
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

      {/* 2. Metadata + era */}
      <div className="wizard-step">
        <h3>2 · Metadata &amp; era</h3>
        <div className="row">
          <label>
            Title
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="override / detected"
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
            Era
            <input
              type="text"
              value={era}
              onChange={(e) => setEra(e.target.value)}
              placeholder="e.g. late-Victorian"
            />
          </label>
        </div>
        <p className="muted" style={{ marginTop: 4 }}>
          Era rides in every prompt (§4.3). Set it from the author’s period; leave blank to let the
          bake default it.
        </p>
      </div>

      {/* 3. Style picker */}
      <div className="wizard-step">
        <h3>3 · Style</h3>
        <ErrorNotice error={styles.error} prefix="Could not load styles" />
        <p className="muted" style={{ marginTop: 0 }}>
          Swatches are placeholders (real samples land at M1).
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
                {s.consistency_friendly ? "consistency-friendly" : "may drift"}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 4. Density */}
      <div className="wizard-step">
        <h3>4 · Density</h3>
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

      {/* 5. Portraits */}
      <div className="wizard-step">
        <h3>5 · Portraits</h3>
        <label>
          <input
            type="checkbox"
            checked={portraits}
            onChange={(e) => setPortraits(e.target.checked)}
          />
          Generate character portraits for majors
        </label>
      </div>

      <ErrorNotice error={submitError} prefix="Create failed" />

      <div className="row">
        <button className="primary" disabled={!canCreate} onClick={onCreate}>
          {submitting ? "Creating…" : "Create book"}
        </button>
        <button onClick={() => navigate({ name: "list" })}>Cancel</button>
        {!sourceReady && <span className="muted">Add a source to continue.</span>}
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
          aria-label="gutendex query"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search Project Gutenberg…"
          style={{ minWidth: 260 }}
        />
        <button type="submit" disabled={loading || !q.trim()}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>
      <ErrorNotice error={error} prefix="Gutendex search failed" />
      {results && results.length === 0 && <p className="muted">No matches.</p>}
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
                    {r.authors.join(", ") || "unknown author"} · #{r.id}
                    {!r.download_url && " · no plain-text edition"}
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
