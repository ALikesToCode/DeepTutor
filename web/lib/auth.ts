export const AUTH_COOKIE_NAME = "deeptutor_access";

const ENABLED_VALUES = new Set(["1", "true", "yes", "on"]);
const DISABLED_VALUES = new Set(["0", "false", "no", "off"]);
const DEFAULT_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

type Env = Record<string, string | undefined>;

export interface AuthSettings {
  enabled: boolean;
  passwordConfigured: boolean;
  password: string;
}

function envValue(env: Env, name: string): string {
  return String(env[name] ?? "").trim();
}

export function readAuthSettings(env: Env = process.env): AuthSettings {
  const password = envValue(env, "DEEPTUTOR_AUTH_PASSWORD");
  const flag = envValue(env, "DEEPTUTOR_AUTH_ENABLED").toLowerCase();
  const passwordConfigured = password.length > 0;

  if (DISABLED_VALUES.has(flag)) {
    return { enabled: false, passwordConfigured, password };
  }

  return {
    enabled: passwordConfigured || ENABLED_VALUES.has(flag),
    passwordConfigured,
    password,
  };
}

export function authMaxAgeSeconds(env: Env = process.env): number {
  const parsed = Number.parseInt(envValue(env, "DEEPTUTOR_AUTH_MAX_AGE_SECONDS"), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : DEFAULT_MAX_AGE_SECONDS;
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

export function verifyPassword(candidate: string, env: Env = process.env): boolean {
  const settings = readAuthSettings(env);
  if (!settings.passwordConfigured) return false;
  return constantTimeEqual(candidate, settings.password);
}

export async function createAuthToken(env: Env = process.env): Promise<string> {
  const settings = readAuthSettings(env);
  if (!settings.passwordConfigured) return "";

  const secret = envValue(env, "DEEPTUTOR_AUTH_SECRET") || settings.password;
  const material = `deeptutor-auth:v1:${settings.password}:${secret}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(material));
  return `v1.${base64Url(new Uint8Array(digest))}`;
}

export async function verifyAuthToken(
  token: string | undefined,
  env: Env = process.env,
): Promise<boolean> {
  if (!token) return false;
  const expected = await createAuthToken(env);
  if (!expected) return false;
  return constantTimeEqual(token, expected);
}
