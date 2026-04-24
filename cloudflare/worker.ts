import { Container, getContainer, switchPort } from "@cloudflare/containers";
import { env as cloudflareEnv } from "cloudflare:workers";

interface Env {
  DEEPTUTOR_CONTAINER: DurableObjectNamespace<DeepTutorContainer>;
}

const stringEnv = cloudflareEnv as unknown as Record<string, string | undefined>;

const DEFAULT_ENV = {
  BACKEND_PORT: "8001",
  FRONTEND_PORT: "3782",
  NEXT_PUBLIC_API_BASE_EXTERNAL: "same-origin",
  LLM_BINDING: "openai",
  LLM_MODEL: "gpt-4o-mini",
  LLM_HOST: "https://api.openai.com/v1",
  LLM_API_VERSION: "",
  EMBEDDING_BINDING: "openai",
  EMBEDDING_MODEL: "text-embedding-3-large",
  EMBEDDING_HOST: "https://api.openai.com/v1",
  EMBEDDING_DIMENSION: "3072",
  EMBEDDING_SEND_DIMENSIONS: "",
  EMBEDDING_API_VERSION: "",
  NAVY_API_BASE: "https://api.navy/v1",
  NAVY_IMAGE_MODEL: "gpt-image-2",
  NAVY_VIDEO_MODEL: "grok-imagine-video",
  SEARCH_PROVIDER: "",
  SEARCH_BASE_URL: "",
  SEARCH_PROXY: "",
  DISABLE_SSL_VERIFY: "false",
  ENVIRONMENT: "production",
} as const;

const SECRET_ENV_NAMES = [
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
  "DEEPSEEK_API_KEY",
  "GEMINI_API_KEY",
  "GOOGLE_GENERATIVE_AI_API_KEY",
  "GOOGLE_API_KEY",
  "DASHSCOPE_API_KEY",
  "GROQ_API_KEY",
  "MISTRAL_API_KEY",
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
  return url.pathname === "/api" || url.pathname.startsWith("/api/");
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/_worker/health") {
      return Response.json({ ok: true, service: "deeptutor" });
    }

    const container = getContainer(env.DEEPTUTOR_CONTAINER);

    if (isBackendRequest(request)) {
      return container.fetch(switchPort(request, BACKEND_PORT));
    }

    return container.fetch(request);
  },
};
