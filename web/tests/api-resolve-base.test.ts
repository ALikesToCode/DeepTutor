import test from "node:test";
import assert from "node:assert/strict";

// Must be set before importing the module under test, since API_BASE_URL is
// read at module-load time and the module throws if it's missing.
const DEFAULT_API_BASE = "http://localhost:8001/api";

function loadApiModule(base = DEFAULT_API_BASE): typeof import("../lib/api") {
  process.env.NEXT_PUBLIC_API_BASE = base;
  const modulePath = require.resolve("../lib/api");
  delete require.cache[modulePath];
  return require("../lib/api") as typeof import("../lib/api");
}

function setWindow(hostname: string | undefined, origin?: string): void {
  if (hostname === undefined) {
    delete (globalThis as { window?: unknown }).window;
    return;
  }
  (globalThis as { window?: unknown }).window = {
    location: { hostname, origin: origin ?? `http://${hostname}:3782` },
  } as unknown;
}

test("resolveBase returns the build-time base in SSR (no window)", () => {
  const { resolveBase } = loadApiModule();
  setWindow(undefined);
  assert.equal(resolveBase(), "http://localhost:8001/api");
});

test("resolveBase returns base unchanged when client is also on localhost", () => {
  const { resolveBase } = loadApiModule();
  setWindow("localhost");
  assert.equal(resolveBase(), "http://localhost:8001/api");
});

test("resolveBase rewrites loopback hostname to remote LAN host and preserves path", () => {
  const { resolveBase } = loadApiModule();
  setWindow("192.168.1.10");
  assert.equal(resolveBase(), "http://192.168.1.10:8001/api");
});

test("resolveBase treats IPv6 loopback as loopback (no swap when client is also ::1)", () => {
  const { resolveBase } = loadApiModule();
  setWindow("::1");
  assert.equal(resolveBase(), "http://localhost:8001/api");
});

test("apiUrl composes correctly after rewrite, without losing the base path", () => {
  const { apiUrl } = loadApiModule();
  setWindow("10.0.0.5");
  assert.equal(
    apiUrl("/api/v1/knowledge/list"),
    "http://10.0.0.5:8001/api/api/v1/knowledge/list",
  );
});

test("wsUrl converts http to ws and respects rewritten host", () => {
  const { wsUrl } = loadApiModule();
  setWindow("10.0.0.5");
  assert.equal(wsUrl("/api/v1/ws"), "ws://10.0.0.5:8001/api/api/v1/ws");
});

test("wsUrl keeps original loopback when client is also loopback", () => {
  const { wsUrl } = loadApiModule();
  setWindow("127.0.0.1");
  assert.equal(wsUrl("/api/v1/ws"), "ws://localhost:8001/api/api/v1/ws");
});

test("same-origin API base resolves to the page origin for Cloudflare proxying", () => {
  const { apiUrl, resolveBase, wsUrl } = loadApiModule("same-origin");
  setWindow("deeptutor.example.com", "https://deeptutor.example.com");
  assert.equal(resolveBase(), "https://deeptutor.example.com");
  assert.equal(
    apiUrl("/api/v1/knowledge/list"),
    "https://deeptutor.example.com/api/v1/knowledge/list",
  );
  assert.equal(wsUrl("/api/v1/ws"), "wss://deeptutor.example.com/api/v1/ws");
});
