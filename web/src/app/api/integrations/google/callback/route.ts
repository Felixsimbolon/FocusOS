import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken, getServerUser } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import {
  GOOGLE_STATE_COOKIE,
  googleRedirectUri,
  readGoogleOAuthCodeVerifier,
} from "@/server/google/oauth";

export async function GET(request: NextRequest) {
  const appUrl = requireServerEnv("FOCUSOS_APP_URL");
  const user = await getServerUser();
  const parameters = request.nextUrl.searchParams;
  const state = parameters.get("state");
  const signedState = request.cookies.get(GOOGLE_STATE_COOKIE)?.value;
  const codeVerifier = readGoogleOAuthCodeVerifier(signedState, state, user?.id ?? null);
  const validState = codeVerifier !== null;

  let outcome: string;
  if (!validState) {
    outcome = "invalid_state";
  } else if (parameters.has("error")) {
    outcome = "cancelled";
  } else {
    const code = parameters.get("code");
    const accessToken = await getServerAccessToken();
    if (!code || !accessToken || !codeVerifier) {
      outcome = "exchange_failed";
    } else {
      try {
        const apiUrl = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
        const apiResponse = await fetch(apiUrl + "/connections/google/authorize", {
          method: "POST",
          headers: {
            "Authorization": "Bearer " + accessToken,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            code,
            code_verifier: codeVerifier,
            redirect_uri: googleRedirectUri(appUrl),
          }),
          cache: "no-store",
        });
        outcome = apiResponse.ok ? "connected" : "exchange_failed";
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
