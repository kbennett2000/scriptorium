import "@testing-library/jest-dom/vitest";

import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// RTL doesn't auto-clean with globals off; unmount between tests and reset the hash router.
afterEach(() => {
  cleanup();
  window.location.hash = "";
});
