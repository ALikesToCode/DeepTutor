import { NextResponse, type NextRequest } from "next/server";
import {
  AUTH_COOKIE_NAME,
  readAuthSettings,
  verifyAuthToken,
} from "@/lib/auth";

const PUBLIC_PATHS = new Set([
  "/login",
  "/favicon.ico",
  "/favicon-16x16.png",
  "/favicon-32x32.png",
  "/apple-touch-icon.png",
  "/logo.png",
  "/logo-ver2.png",
  "/api/version",
]);

function isPublicRequest(pathname: string): boolean {
  return (
    PUBLIC_PATHS.has(pathname) ||
    pathname.startsWith("/api/auth/") ||
    pathname.startsWith("/_next/")
  );
}

function wantsHtml(request: NextRequest): boolean {
  const accept = request.headers.get("accept") ?? "";
  return accept.includes("text/html") || accept === "*/*";
}

function safeNextPath(request: NextRequest): string {
  return `${request.nextUrl.pathname}${request.nextUrl.search}`;
}

export async function proxy(request: NextRequest) {
  const settings = readAuthSettings();

  if (!settings.enabled || !settings.passwordConfigured || isPublicRequest(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const authenticated = await verifyAuthToken(request.cookies.get(AUTH_COOKIE_NAME)?.value);
  if (authenticated) {
    return NextResponse.next();
  }

  if (!wantsHtml(request)) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  loginUrl.searchParams.set("next", safeNextPath(request));

  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
