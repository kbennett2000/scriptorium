import { useEffect, useState } from "react";

import type { BundleReader } from "./BundleReader";

// A page's plate, at the top of its logical page, full-width (DESIGN §13 ADR-0004). The image comes
// from the BundleReader as a local object/data URL — never a network fetch. Tap → lightbox (handled by
// the parent via onOpen). Renders nothing if the reader has no image for this page (e.g. a plate whose
// web derivative isn't resident); retired plates are filtered out before this component is used.
//
// `caption` is the page's depicted-moment line (the scene ledger's `best_visual_beat`, derived only
// from this page's own text — spoiler-safe). It renders as a <figcaption> under the image so the
// reader knows which moment of the page the picture shows. Absent/blank → no caption element.
//
// ADR-0037: if the profile accepted a video clip for this plate (in the active scope), a play button
// overlays the still; clicking it swaps in an inline <video> that plays from a local blob URL (still
// zero-online — the mp4 is Resident in the overlay). It reverts to the still when the clip ends.

export function Plate({
  reader,
  relPath,
  plateId,
  alt,
  caption = null,
  onOpen,
}: {
  reader: BundleReader;
  relPath: string;
  plateId: string;
  alt: string;
  caption?: string | null;
  onOpen: (src: string) => void;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [videoSrc, setVideoSrc] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void reader.imageUrl(relPath).then((url) => {
      if (live) setSrc(url);
    });
    return () => {
      live = false;
    };
  }, [reader, relPath]);

  // A new reader (e.g. after a video is accepted) or plate resets any playing clip.
  useEffect(() => setVideoSrc(null), [reader, plateId]);

  const hasVideo = reader.hasVideo?.(plateId) ?? false;

  async function play() {
    const url = await reader.videoUrl?.(plateId);
    if (url) setVideoSrc(url);
  }

  if (!src) return null;

  return (
    <figure className="plate">
      {videoSrc ? (
        <video
          className="plate-img plate-video"
          src={videoSrc}
          controls
          autoPlay
          playsInline
          onEnded={() => setVideoSrc(null)}
        />
      ) : (
        <div className="plate-frame">
          <img
            className="plate-img"
            src={src}
            alt={alt}
            onClick={() => onOpen(src)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen(src);
              }
            }}
          />
          {hasVideo && (
            <button
              type="button"
              className="plate-play"
              aria-label="Play video"
              onClick={(e) => {
                e.stopPropagation();
                void play();
              }}
            >
              <span className="plate-play-glyph" aria-hidden="true">
                ▶
              </span>
            </button>
          )}
        </div>
      )}
      {caption && <figcaption className="plate-caption">{caption}</figcaption>}
    </figure>
  );
}
