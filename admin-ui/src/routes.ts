// A deliberately tiny hash router — no react-router dependency (S9b executor's call; recorded in
// CYCLE-LOG). The admin UI has five destinations; a discriminated union + location.hash is enough
// and keeps the workbench dependency-free. Deep-linking/refresh work because the hash carries the
// full route.

import { useEffect, useState } from "react";

export type Route =
  | { name: "list" }
  | { name: "wizard" }
  | { name: "detail"; id: string }
  | { name: "review"; id: string }
  | { name: "postrender"; id: string };

export function routeToHash(route: Route): string {
  switch (route.name) {
    case "list":
      return "#/";
    case "wizard":
      return "#/new";
    case "detail":
      return `#/book/${route.id}`;
    case "review":
      return `#/book/${route.id}/review`;
    case "postrender":
      return `#/book/${route.id}/postrender`;
  }
}

export function hashToRoute(hash: string): Route {
  const path = hash.replace(/^#/, "");
  if (path === "" || path === "/") return { name: "list" };
  if (path === "/new") return { name: "wizard" };
  const m = path.match(/^\/book\/([^/]+)(?:\/(review|postrender))?$/);
  if (m) {
    const id = decodeURIComponent(m[1]);
    if (m[2] === "review") return { name: "review", id };
    if (m[2] === "postrender") return { name: "postrender", id };
    return { name: "detail", id };
  }
  return { name: "list" };
}

export function navigate(route: Route): void {
  const hash = routeToHash(route);
  if (window.location.hash !== hash) {
    window.location.hash = hash;
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => hashToRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(hashToRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
