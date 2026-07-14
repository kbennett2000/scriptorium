import { useEffect, useState } from "react";

// Plate lightbox (DESIGN §13 ADR-0004): a full-screen overlay over the current plate. Backdrop click
// or Esc closes; clicking the image toggles a basic 1×/2× zoom (pinch-zoom on touch is the browser's
// native gesture on the zoomed image). Minimal by design — the designed skin is R4.

export function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const [zoomed, setZoomed] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={alt} onClick={onClose}>
      <img
        className={zoomed ? "lightbox-img zoomed" : "lightbox-img"}
        src={src}
        alt={alt}
        onClick={(e) => {
          e.stopPropagation();
          setZoomed((z) => !z);
        }}
      />
      <button type="button" className="lightbox-close" aria-label="Close" onClick={onClose}>
        ×
      </button>
    </div>
  );
}
