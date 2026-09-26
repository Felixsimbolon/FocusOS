import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken, getServerUser } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import {
  GOOGLE_STATE_COOKIE,
  googleRedirectUri,
  readGoogleOAuthContext,
} from "@/server/google/oauth";

export async function GET(request: NextRequest) {
  const appUrl = requireServerEnv("FOCUSOS_APP_URL");
  const user = await getServerUser();
  const parameters = request.nextUrl.searchParams;
  const state = parameters.get("state");
  const signedState = request.cookies.get(GOOGLE_STATE_COOKIE)?.value;
  const oauthContext = readGoogleOAuthContext(signedState, state, user?.id ?? null);
  const validState = oauthContext !== null;

  let outcome: string;
  if (!validState) {
    outcome = "invalid_state";
  } else if (parameters.has("error")) {
    outcome = "cancelled";
  } else {
    const code = parameters.get("code");
    const accessToken = await getServerAccessToken();
    if (!code || !accessToken || !oauthContext) {
      outcome = "exchange_failed";
    } else {
      try {
        const apiUrl = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
        const calendarWriteUpgrade = oauthContext.flow === "calendar_write";
        const apiPath = calendarWriteUpgrade
          ? "/connections/google/calendar-write/authorize"
          : "/connections/google/authorize";
        const apiResponse = await fetch(apiUrl + apiPath, {
          method: "POST",
          headers: {
            "Authorization": "Bearer " + accessToken,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            code,
            code_verifier: oauthContext.codeVerifier,
            redirect_uri: googleRedirectUri(appUrl),
          }),
          cache: "no-store",
        });
        outcome = apiResponse.ok ? (calendarWriteUpgrade ? "calendar_write_granted" : "connected") : "exchange_failed";
      } catch {
        outcome = "exchange_failed";
      }
    }
  }

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
