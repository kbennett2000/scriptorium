// Public surface of the annotations feature (R2). Anchor math + overlap painting + the local store are
// pure/logic; the components are the selection bar, note sheet, and per-book list.

export { domRangeToAnchor, anchorToDomRange } from "./anchors";
export type { Anchor } from "./anchors";
export { paintParagraph } from "./segments";
export type { HighlightColor, Run, Span } from "./segments";
export {
  DEV_USER_ID,
  readAnnotations,
  liveAnnotations,
  hasBookmark,
  createHighlight,
  createNote,
  updateAnnotation,
  deleteAnnotation,
  toggleBookmark,
} from "./store";
export type { Annotation } from "./store";
export { SelectionBar } from "./SelectionBar";
export { NoteSheet } from "./NoteSheet";
export { AnnotationsPanel } from "./AnnotationsPanel";
