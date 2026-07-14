import type { Storage } from "./storage";

// Android/iOS `Storage` over `@capacitor/filesystem` (Directory.Data), per DESIGN §13 / ADR-0006.
// The class exists now so `shell/index.ts` can select it by platform, but its body — and the
// `@capacitor/*` dependency — land in R5 (Capacitor build + persistence hardening). Until then any
// call throws loudly rather than silently no-op'ing.

const NOT_YET = "CapacitorStorage is implemented in R5 (Capacitor build); use OpfsStorage on desktop.";

export class CapacitorStorage implements Storage {
  async readText(): Promise<string> {
    throw new Error(NOT_YET);
  }
  async readBytes(): Promise<Uint8Array> {
    throw new Error(NOT_YET);
  }
  async writeText(): Promise<void> {
    throw new Error(NOT_YET);
  }
  async writeBytes(): Promise<void> {
    throw new Error(NOT_YET);
  }
  async exists(): Promise<boolean> {
    throw new Error(NOT_YET);
  }
  async delete(): Promise<void> {
    throw new Error(NOT_YET);
  }
  async list(): Promise<string[]> {
    throw new Error(NOT_YET);
  }
}
