import { useEffect, useRef } from "react";

// A tiny LIFO stack of "back" handlers (R5). The Android hardware-back / gesture-back is routed here
// by initNativeShell (see ./native): the most-recently-mounted view that registered a handler gets
// first refusal, so an open overlay consumes Back before the reader turns a page, and the reader
// consumes it before the app backgrounds. A handler returns true if it consumed the press.
//
// This is pure and platform-agnostic — on the web nothing ever calls handleBack(), so registering is
// a harmless no-op and the desktop/e2e behaviour is unchanged.

type BackHandler = () => boolean;

const stack: BackHandler[] = [];

/** Register a back handler on top of the stack; returns an unsubscribe that removes exactly it. */
export function pushBackHandler(handler: BackHandler): () => void {
  stack.push(handler);
  return () => {
    const i = stack.lastIndexOf(handler);
    if (i >= 0) stack.splice(i, 1);
  };
}

/** Invoke handlers top-down; stop at the first that consumes the press. False = nothing handled it. */
export function handleBack(): boolean {
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    if (stack[i]()) return true;
  }
  return false;
}

/**
 * Register `handler` for the lifetime of the component. The latest closure is always used (via a ref),
 * so the handler sees current state without churning its position in the stack on every render.
 */
export function useBackHandler(handler: BackHandler): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => pushBackHandler(() => ref.current()), []);
}
