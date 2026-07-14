import type { Storage } from "./storage";
import { splitPath } from "./storage";

// In-memory `Storage` for tests and non-persistent previews. It is the reference implementation the
// storage-contract test pins every backend against — OPFS is unavailable under jsdom, so this is
// where the interface's semantics are actually asserted.

export class MemoryStorage implements Storage {
  private files = new Map<string, Uint8Array>();

  private key(path: string): string {
    return splitPath(path).join("/");
  }

  async readBytes(path: string): Promise<Uint8Array> {
    const bytes = this.files.get(this.key(path));
    if (bytes === undefined) throw new Error(`no such file: ${path}`);
    return bytes;
  }

  async readText(path: string): Promise<string> {
    return new TextDecoder().decode(await this.readBytes(path));
  }

  async writeBytes(path: string, data: Uint8Array): Promise<void> {
    this.files.set(this.key(path), data);
  }

  async writeText(path: string, data: string): Promise<void> {
    await this.writeBytes(path, new TextEncoder().encode(data));
  }

  async exists(path: string): Promise<boolean> {
    return this.files.has(this.key(path));
  }

  async delete(path: string): Promise<void> {
    const key = this.key(path);
    if (this.files.delete(key)) return;
    // Directory delete: drop everything under `key/`.
    const dirPrefix = `${key}/`;
    for (const existing of [...this.files.keys()]) {
      if (existing.startsWith(dirPrefix)) this.files.delete(existing);
    }
  }

  async list(prefix: string): Promise<string[]> {
    const parts = splitPath(prefix);
    const dirPrefix = parts.length ? `${parts.join("/")}/` : "";
    const out: string[] = [];
    for (const key of this.files.keys()) {
      if (key === parts.join("/") || key.startsWith(dirPrefix)) out.push(key);
    }
    return out;
  }
}
