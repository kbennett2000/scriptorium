import type { Storage } from "./storage";
import { splitPath } from "./storage";

// Desktop-PWA `Storage` over the Origin-Private File System (DESIGN §13, ADR-0006). OPFS is
// synchronous-durable, origin-scoped, and not user-visible — ideal for owned book bundles. On first
// checkout the app also calls `navigator.storage.persist()` (see BrowserPlatform) so the browser
// won't evict us under storage pressure.
//
// OPFS is a handle tree, so every op walks `books/usr-…/pages/0001.json` segment by segment. Not
// unit-tested here (jsdom has no OPFS) — exercised in the R1b real-browser offline-acceptance run.

export class OpfsStorage implements Storage {
  private async root(): Promise<FileSystemDirectoryHandle> {
    return navigator.storage.getDirectory();
  }

  /** Walk to the directory holding `path`'s leaf, returning [dirHandle, leafName]. */
  private async resolveParent(
    path: string,
    create: boolean,
  ): Promise<[FileSystemDirectoryHandle, string]> {
    const parts = splitPath(path);
    if (parts.length === 0) throw new Error("empty storage path");
    const leaf = parts[parts.length - 1];
    let dir = await this.root();
    for (const seg of parts.slice(0, -1)) {
      dir = await dir.getDirectoryHandle(seg, { create });
    }
    return [dir, leaf];
  }

  async readBytes(path: string): Promise<Uint8Array> {
    const [dir, leaf] = await this.resolveParent(path, false);
    const handle = await dir.getFileHandle(leaf);
    const file = await handle.getFile();
    return new Uint8Array(await file.arrayBuffer());
  }

  async readText(path: string): Promise<string> {
    return new TextDecoder().decode(await this.readBytes(path));
  }

  async writeBytes(path: string, data: Uint8Array): Promise<void> {
    const [dir, leaf] = await this.resolveParent(path, true);
    const handle = await dir.getFileHandle(leaf, { create: true });
    const writable = await handle.createWritable();
    // Copy into a fresh ArrayBuffer to satisfy the BufferSource write type (Uint8Array is generic
    // over ArrayBufferLike in TS 5.9+).
    const buf = new ArrayBuffer(data.byteLength);
    new Uint8Array(buf).set(data);
    await writable.write(buf);
    await writable.close();
  }

  async writeText(path: string, data: string): Promise<void> {
    await this.writeBytes(path, new TextEncoder().encode(data));
  }

  async exists(path: string): Promise<boolean> {
    try {
      const [dir, leaf] = await this.resolveParent(path, false);
      // Either a file or a directory of that name counts as existing.
      try {
        await dir.getFileHandle(leaf);
      } catch {
        await dir.getDirectoryHandle(leaf);
      }
      return true;
    } catch {
      return false;
    }
  }

  async delete(path: string): Promise<void> {
    let dir: FileSystemDirectoryHandle;
    let leaf: string;
    try {
      [dir, leaf] = await this.resolveParent(path, false);
    } catch {
      return; // a missing parent directory means nothing to delete
    }
    try {
      await dir.removeEntry(leaf, { recursive: true });
    } catch {
      // already absent — deletion is idempotent
    }
  }

  async list(prefix: string): Promise<string[]> {
    const parts = splitPath(prefix);
    let dir = await this.root();
    try {
      for (const seg of parts) {
        dir = await dir.getDirectoryHandle(seg);
      }
    } catch {
      return []; // prefix dir doesn't exist
    }
    const out: string[] = [];
    await this.walk(dir, parts.join("/"), out);
    return out;
  }

  private async walk(
    dir: FileSystemDirectoryHandle,
    prefix: string,
    out: string[],
  ): Promise<void> {
    // OPFS directory handles are async-iterable over [name, handle], but the DOM lib in TS 5.9 does
    // not yet declare `entries()` on FileSystemDirectoryHandle — narrow through a local shape.
    const iterable = dir as unknown as {
      entries(): AsyncIterableIterator<[string, FileSystemHandle]>;
    };
    for await (const [name, handle] of iterable.entries()) {
      const childPath = prefix ? `${prefix}/${name}` : name;
      if (handle.kind === "file") {
        out.push(childPath);
      } else {
        await this.walk(handle as FileSystemDirectoryHandle, childPath, out);
      }
    }
  }
}
