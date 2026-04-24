import { NextResponse, type NextRequest } from "next/server";
import { AUTH_COOKIE_NAME, readAuthSettings, verifyAuthToken } from "@/lib/auth";

export async function GET(request: NextRequest) {
  const settings = readAuthSettings();
  const authenticated =
    !settings.enabled ||
    (settings.passwordConfigured &&
      (await verifyAuthToken(request.cookies.get(AUTH_COOKIE_NAME)?.value)));

  return NextResponse.json({
    enabled: settings.enabled,
    configured: settings.passwordConfigured,
    authenticated,
  });
}
