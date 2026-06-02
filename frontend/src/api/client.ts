import axios from "axios";

// Same-origin in prod (FastAPI serves the SPA); proxied in dev (vite.config.ts).
// withCredentials so the session cookie rides along when the login gate is on.
export const api = axios.create({
  baseURL: "/api",
  withCredentials: true,
  // Serialize array params as repeated keys (reports=a&reports=b) — what
  // FastAPI's Query(list) expects.
  paramsSerializer: { indexes: null },
});
