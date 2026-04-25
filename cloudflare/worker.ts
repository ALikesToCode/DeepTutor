import { Container, getContainer, switchPort } from "@cloudflare/containers";
import { env as cloudflareEnv } from "cloudflare:workers";

interface Env {
  DEEPTUTOR_CONTAINER: DurableObjectNamespace<DeepTutorContainer>;
  DEEPTUTOR_FILES?: R2Bucket;
  DEEPTUTOR_R2_SYNC_TOKEN?: string;
}

const stringEnv = cloudflareEnv as unknown as Record<string, string | undefined>;

const DEFAULT_ENV = {
  BACKEND_PORT: "8001",
  FRONTEND_PORT: "3782",
  DEEPTUTOR_AUTH_ENABLED: "",
  DEEPTUTOR_AUTH_MAX_AGE_SECONDS: "604800",
  NEXT_PUBLIC_API_BASE_EXTERNAL: "same-origin",
  LLM_BINDING: "navy",
  LLM_MODEL: "gpt-5.4-mini",
  LLM_HOST: "https://api.navy/v1",
  LLM_API_VERSION: "",
  EMBEDDING_BINDING: "navy",
  EMBEDDING_MODEL: "gemini-embedding-2-preview",
  EMBEDDING_HOST: "https://api.navy/v1",
  EMBEDDING_DIMENSION: "3072",
  EMBEDDING_SEND_DIMENSIONS: "false",
  EMBEDDING_API_VERSION: "",
  NAVY_API_BASE: "https://api.navy/v1",
  NAVY_IMAGE_MODEL: "gpt-image-2",
  NAVY_VIDEO_MODEL: "grok-imagine-video",
  SEARCH_PROVIDER: "",
  SEARCH_BASE_URL: "",
  SEARCH_PROXY: "",
  DEEPTUTOR_R2_OUTPUTS_ENABLED: "",
  DEEPTUTOR_R2_OUTPUTS_PREFIX: "outputs/",
  DEEPTUTOR_R2_STATE_SYNC_ENABLED: "",
  DEEPTUTOR_R2_STATE_SNAPSHOT_KEY: "state/data.tar.gz",
  DEEPTUTOR_R2_SYNC_INTERVAL_SECONDS: "300",
  DEEPTUTOR_R2_SYNC_REQUEST_TIMEOUT_SECONDS: "20",
  DEEPTUTOR_R2_SYNC_URL: "",
  DISABLE_SSL_VERIFY: "false",
  ENVIRONMENT: "production",
} as const;

const SECRET_ENV_NAMES = [
  "DEEPTUTOR_AUTH_PASSWORD",
  "DEEPTUTOR_AUTH_SECRET",
  "DEEPTUTOR_R2_SYNC_TOKEN",
  "LLM_API_KEY",
  "EMBEDDING_API_KEY",
  "SEARCH_API_KEY",
  "OPENAI_API_KEY",
  "OPENAI_BASE_URL",
  "ANTHROPIC_API_KEY",
  "AZURE_OPENAI_API_KEY",
  "AZURE_API_KEY",
  "BRAVE_API_KEY",
  "TAVILY_API_KEY",
  "JINA_API_KEY",
  "PERPLEXITY_API_KEY",
  "SERPER_API_KEY",
  "OPENROUTER_API_KEY",
  "NAVY_API_KEY",
  "COHERE_API_KEY",
  "DEEPSEEK_API_KEY",
  "GEMINI_API_KEY",
  "GOOGLE_GENERATIVE_AI_API_KEY",
  "GOOGLE_API_KEY",
  "ZAI_API_KEY",
  "ZHIPUAI_API_KEY",
  "DASHSCOPE_API_KEY",
  "GROQ_API_KEY",
  "MOONSHOT_API_KEY",
  "MINIMAX_API_KEY",
  "MISTRAL_API_KEY",
  "STEPFUN_API_KEY",
  "XIAOMIMIMO_API_KEY",
  "QIANFAN_API_KEY",
  "HOSTED_VLLM_API_KEY",
  "OLLAMA_API_KEY",
  "LM_STUDIO_API_KEY",
] as const;

function envValue(name: string, fallback = ""): string {
  const value = stringEnv[name];
  return value == null || value === "" ? fallback : value;
}

function envPort(name: string, fallback: number): number {
  const parsed = Number.parseInt(envValue(name), 10);
  return Number.isInteger(parsed) && parsed > 0 && parsed <= 65535 ? parsed : fallback;
}

function buildContainerEnv(): Record<string, string> {
  const values: Record<string, string> = {};

  for (const [name, fallback] of Object.entries(DEFAULT_ENV)) {
    values[name] = envValue(name, fallback);
  }

  for (const name of SECRET_ENV_NAMES) {
    const value = envValue(name);
    if (value) values[name] = value;
  }

  return values;
}

const BACKEND_PORT = envPort("BACKEND_PORT", 8001);
const FRONTEND_PORT = envPort("FRONTEND_PORT", 3782);
const AUTH_COOKIE_NAME = "deeptutor_access";
const CONTAINER_ENTRYPOINT = ["/bin/bash", "/app/entrypoint.sh"];
const START_TIMEOUTS = {
  instanceGetTimeoutMS: 120_000,
  portReadyTimeoutMS: 180_000,
  waitInterval: 1_000,
};

export class DeepTutorContainer extends Container {
  defaultPort = FRONTEND_PORT;
  requiredPorts = [BACKEND_PORT, FRONTEND_PORT];
  sleepAfter = "2h";
  entrypoint = CONTAINER_ENTRYPOINT;
  envVars = buildContainerEnv();

  async fetch(request: Request): Promise<Response> {
    const targetPort = request.headers.has("cf-container-target-port")
      ? Number.parseInt(request.headers.get("cf-container-target-port") ?? "", 10)
      : this.defaultPort;

    if (!Number.isInteger(targetPort)) {
      return new Response("No valid container port configured.", { status: 500 });
    }

    try {
      await this.startAndWaitForPorts({
        ports: targetPort,
        startOptions: {
          envVars: this.envVars,
          entrypoint: CONTAINER_ENTRYPOINT,
          enableInternet: true,
        },
        cancellationOptions: {
          abort: request.signal,
          ...START_TIMEOUTS,
        },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return new Response(`Failed to start container: ${message}`, { status: 500 });
    }

    return this.containerFetch(request, targetPort);
  }
}

function isBackendRequest(request: Request): boolean {
  const url = new URL(request.url);
  if (url.pathname === "/api/auth" || url.pathname.startsWith("/api/auth/")) {
    return false;
  }
  if (url.pathname === "/api/version") {
    return false;
  }
  return url.pathname === "/api" || url.pathname.startsWith("/api/");
}

function isWebSocketUpgrade(request: Request): boolean {
  return request.headers.get("upgrade")?.toLowerCase() === "websocket";
}

function isR2StateSyncEnabled(env: Env): boolean {
  if (!env.DEEPTUTOR_FILES || !env.DEEPTUTOR_R2_SYNC_TOKEN) return false;

  const flag = envValue("DEEPTUTOR_R2_STATE_SYNC_ENABLED").trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(flag);
}

function isAuthorizedR2StateSyncRequest(request: Request, env: Env): boolean {
  const token = env.DEEPTUTOR_R2_SYNC_TOKEN ?? "";
  const authorization = request.headers.get("authorization") ?? "";
  const prefix = "Bearer ";
  if (!token || !authorization.startsWith(prefix)) {
    return false;
  }
  return constantTimeEqual(authorization.slice(prefix.length), token);
}

async function handleR2StateSnapshot(request: Request, env: Env): Promise<Response> {
  if (!isR2StateSyncEnabled(env) || !env.DEEPTUTOR_FILES) {
    return new Response("R2 state sync is not configured.", { status: 404 });
  }
  if (!isAuthorizedR2StateSyncRequest(request, env)) {
    return new Response("Unauthorized.", { status: 401 });
  }

  const key = envValue(
    "DEEPTUTOR_R2_STATE_SNAPSHOT_KEY",
    DEFAULT_ENV.DEEPTUTOR_R2_STATE_SNAPSHOT_KEY,
  );

  if (request.method === "GET" || request.method === "HEAD") {
    const object = await env.DEEPTUTOR_FILES.get(key);
    if (!object) {
      return new Response(null, { status: 204 });
    }
    return responseFromR2Object(object, request.method);
  }

  if (request.method === "PUT") {
    if (!request.body) {
      return new Response("Snapshot body is required.", { status: 400 });
    }
    await env.DEEPTUTOR_FILES.put(key, request.body, {
      httpMetadata: {
        contentType: request.headers.get("content-type") || "application/gzip",
        cacheControl: "no-store",
      },
    });
    return Response.json({ ok: true, key });
  }

  return new Response("Method not allowed.", {
    status: 405,
    headers: { allow: "GET, HEAD, PUT" },
  });
}

function isR2OutputsEnabled(env: Env): boolean {
  if (!env.DEEPTUTOR_FILES) return false;

  const flag = envValue("DEEPTUTOR_R2_OUTPUTS_ENABLED").trim().toLowerCase();
  if (["0", "false", "no", "off"].includes(flag)) {
    return false;
  }

  return true;
}

function isAllowedOutputPath(parts: string[]): boolean {
  if (parts.slice(0, 3).join("/") === "workspace/co-writer/audio") {
    return true;
  }

  if (
    parts.length >= 5 &&
    parts.slice(0, 3).join("/") === "workspace/chat/deep_solve" &&
    parts.slice(4).includes("artifacts")
  ) {
    return true;
  }

  if (
    parts.length >= 5 &&
    parts.slice(0, 3).join("/") === "workspace/chat/math_animator" &&
    parts.slice(4).includes("artifacts")
  ) {
    return true;
  }

  if (
    parts.length >= 5 &&
    parts.slice(0, 2).join("/") === "workspace/chat" &&
    parts.slice(3).includes("code_runs")
  ) {
    return true;
  }

  if (
    parts.length >= 4 &&
    parts.slice(0, 3).join("/") === "workspace/chat/_detached_code_execution"
  ) {
    return true;
  }

  return false;
}

function outputR2Key(pathname: string): string | null {
  const prefix = "/api/outputs/";
  if (!pathname.startsWith(prefix)) {
    return null;
  }

  const rawPath = pathname.slice(prefix.length);
  if (!rawPath) {
    return null;
  }

  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(rawPath);
  } catch {
    return null;
  }

  if (decodedPath.includes("\\") || decodedPath.startsWith("/")) {
    return null;
  }

  const parts = decodedPath.split("/");
  if (parts.some((part) => part === "" || part === "." || part === "..")) {
    return null;
  }
  if (!isAllowedOutputPath(parts)) {
    return null;
  }

  const storagePrefix = envValue(
    "DEEPTUTOR_R2_OUTPUTS_PREFIX",
    DEFAULT_ENV.DEEPTUTOR_R2_OUTPUTS_PREFIX,
  )
    .replace(/^\/+/, "")
    .replace(/\/?$/, "/");

  return `${storagePrefix}${parts.join("/")}`;
}

function responseFromR2Object(object: R2ObjectBody, method: string): Response {
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  if (!headers.has("cache-control")) {
    headers.set("cache-control", "private, max-age=3600");
  }

  return new Response(method === "HEAD" ? null : object.body, {
    status: 200,
    headers,
  });
}

function shouldCacheOutputResponse(response: Response): boolean {
  if (!response.ok || !response.body) {
    return false;
  }

  const contentType = response.headers.get("content-type") ?? "";
  return !contentType.includes("text/html");
}

async function cacheOutputResponse(bucket: R2Bucket, key: string, response: Response): Promise<void> {
  if (!shouldCacheOutputResponse(response)) {
    return;
  }

  const metadata: R2HTTPMetadata = {};
  const contentType = response.headers.get("content-type");
  const cacheControl = response.headers.get("cache-control");
  const contentDisposition = response.headers.get("content-disposition");

  if (contentType) metadata.contentType = contentType;
  metadata.cacheControl = cacheControl || "private, max-age=3600";
  if (contentDisposition) metadata.contentDisposition = contentDisposition;

  await bucket.put(key, response.body, { httpMetadata: metadata });
}

async function fetchOutputFromR2OrContainer(
  request: Request,
  env: Env,
  container: DurableObjectStub<DeepTutorContainer>,
  ctx: ExecutionContext,
): Promise<Response | null> {
  if (!isR2OutputsEnabled(env)) {
    return null;
  }

  const url = new URL(request.url);
  const key = outputR2Key(url.pathname);
  const bucket = env.DEEPTUTOR_FILES;
  if (!bucket || !key || !["GET", "HEAD"].includes(request.method)) {
    return null;
  }

  const stored = await bucket.get(key);
  if (stored) {
    return responseFromR2Object(stored, request.method);
  }

  const response = await container.fetch(switchPort(request, BACKEND_PORT));
  if (request.method === "GET" && shouldCacheOutputResponse(response)) {
    ctx.waitUntil(cacheOutputResponse(bucket, key, response.clone()));
  }
  return response;
}

function isAuthEnabled(): boolean {
  const flag = envValue("DEEPTUTOR_AUTH_ENABLED").trim().toLowerCase();
  const password = envValue("DEEPTUTOR_AUTH_PASSWORD").trim();

  if (["0", "false", "no", "off"].includes(flag)) {
    return false;
  }

  return password.length > 0;
}

function isPublicRequest(request: Request): boolean {
  const url = new URL(request.url);
  return (
    url.pathname === "/login" ||
    url.pathname === "/favicon.ico" ||
    url.pathname === "/favicon-16x16.png" ||
    url.pathname === "/favicon-32x32.png" ||
    url.pathname === "/apple-touch-icon.png" ||
    url.pathname === "/logo.png" ||
    url.pathname === "/logo-ver2.png" ||
    url.pathname === "/api/version" ||
    url.pathname.startsWith("/api/auth/") ||
    url.pathname.startsWith("/_next/")
  );
}

function cookieValue(request: Request, name: string): string {
  const cookie = request.headers.get("cookie") ?? "";
  const prefix = `${name}=`;
  for (const part of cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return "";
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;

  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

async function authToken(): Promise<string> {
  const password = envValue("DEEPTUTOR_AUTH_PASSWORD").trim();
  const secret = envValue("DEEPTUTOR_AUTH_SECRET").trim() || password;
  const material = `deeptutor-auth:v1:${password}:${secret}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(material));
  return `v1.${base64Url(new Uint8Array(digest))}`;
}

async function isAuthenticated(request: Request): Promise<boolean> {
  const token = cookieValue(request, AUTH_COOKIE_NAME);
  if (!token) return false;
  return constantTimeEqual(token, await authToken());
}

function wantsHtml(request: Request): boolean {
  const accept = request.headers.get("accept") ?? "";
  return accept.includes("text/html") || accept === "*/*";
}

async function requireAuth(request: Request): Promise<Response | null> {
  if (!isAuthEnabled() || isPublicRequest(request) || (await isAuthenticated(request))) {
    return null;
  }

  if (!wantsHtml(request)) {
    return Response.json({ error: "unauthenticated" }, { status: 401 });
  }

  const requestUrl = new URL(request.url);
  const loginUrl = new URL("/login", requestUrl.origin);
  loginUrl.searchParams.set("next", `${requestUrl.pathname}${requestUrl.search}`);
  return Response.redirect(loginUrl.toString(), 302);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/_worker/health") {
      return Response.json({ ok: true, service: "deeptutor" });
    }
    if (url.pathname === "/_worker/r2-state-snapshot") {
      return handleR2StateSnapshot(request, env);
    }

    const authResponse = await requireAuth(request);
    if (authResponse) {
      return authResponse;
    }

    const container = getContainer(env.DEEPTUTOR_CONTAINER);

    if (isBackendRequest(request)) {
      if (isWebSocketUpgrade(request)) {
        return container.fetch(switchPort(request, BACKEND_PORT));
      }
      const outputResponse = await fetchOutputFromR2OrContainer(request, env, container, ctx);
      if (outputResponse) {
        return outputResponse;
      }
      return container.fetch(switchPort(request, BACKEND_PORT));
    }

    return container.fetch(request);
  },
};
