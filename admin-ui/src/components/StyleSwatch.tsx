// A deterministic inline-SVG placeholder swatch for a style. DESIGN §11.3 wants "pre-rendered
// static samples committed to the repo"; those real samples are deferred to M1 (see NOTES From
// S9b). Until then we derive a stable abstract pattern from the style id so the picker is visually
// distinguishable without shipping image assets or making a network call.

function hashId(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function StyleSwatch({ id }: { id: string }) {
  const h = hashId(id);
  const hue = h % 360;
  const hue2 = (hue + 40 + ((h >> 8) % 80)) % 360;
  const bg = `hsl(${hue} 45% 88%)`;
  const fg = `hsl(${hue2} 55% 40%)`;
  const fg2 = `hsl(${hue} 60% 30%)`;
  // A few deterministic strokes so each style reads differently at a glance.
  const strokes = Array.from({ length: 5 }, (_, i) => {
    const seed = (h >> (i * 3)) & 0xff;
    const y = 12 + i * 22;
    const x2 = 20 + (seed % 130);
    return <line key={i} x1={10} y1={y} x2={x2} y2={y + (seed % 12)} stroke={i % 2 ? fg2 : fg} strokeWidth={2 + (seed % 3)} />;
  });
  return (
    <svg viewBox="0 0 160 120" role="img" aria-label={`${id} placeholder swatch`}>
      <rect width="160" height="120" fill={bg} />
      <circle cx={120 + (h % 20)} cy={30 + (h % 20)} r={18 + (h % 10)} fill={fg} opacity={0.35} />
      {strokes}
    </svg>
  );
}
