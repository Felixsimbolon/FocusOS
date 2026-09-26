import { NextRequest, NextResponse } from "next/server";
import { getServerUser } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import {
  GOOGLE_STATE_COOKIE,
  verifyGoogleOAuthState,
} from "@/server/google/oauth";

export async function GET(request: NextRequest) {
  const appUrl = requireServerEnv("FOCUSOS_APP_URL");
  const user = await getServerUser();
  const parameters = request.nextUrl.searchParams;
  const state = parameters.get("state");
  const signedState = request.cookies.get(GOOGLE_STATE_COOKIE)?.value;
  const validState = verifyGoogleOAuthState(signedState, state, user?.id ?? null);

  const outcome =
    !validState
      ? "invalid_state"
      : parameters.has("error")
        ? "cancelled"
        : parameters.get("code")
          ? "consent_returned"
          : "invalid_state";

  const response = NextResponse.redirect(
    new URL("/settings/connections?google=" + outcome, appUrl),
  );
  response.cookies.set(GOOGLE_STATE_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/api/integrations/google/callback",
    maxAge: 0,
  });
  response.headers.set("Cache-Control", "no-store");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}
