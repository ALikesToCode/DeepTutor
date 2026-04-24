import { NextResponse, type NextRequest } from "next/server";
import {
  AUTH_COOKIE_NAME,
  authMaxAgeSeconds,
  createAuthToken,
  readAuthSettings,
  verifyPassword,
} from "@/lib/auth";

export async function POST(request: NextRequest) {
  const settings = readAuthSettings();

  if (!settings.enabled || !settings.passwordConfigured) {
    return NextResponse.json({ ok: true, disabled: true });
  }

  let password = "";
  try {
    const body = (await request.json()) as { password?: unknown };
    password = typeof body.password === "string" ? body.password : "";
  } catch {
    password = "";
  }

  if (!verifyPassword(password)) {
    return NextResponse.json({ ok: false, error: "invalid_password" }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: AUTH_COOKIE_NAME,
    value: await createAuthToken(),
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: authMaxAgeSeconds(),
  });

  return response;
}
