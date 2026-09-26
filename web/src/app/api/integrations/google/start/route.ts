import { NextRequest, NextResponse } from "next/server";
import { getServerUser } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import {
  createGoogleOAuthState,
  googleAuthorizationUrl,
  googleRedirectUri,
  GOOGLE_STATE_COOKIE,
  GOOGLE_STATE_TTL_SECONDS,
} from "@/server/google/oauth";

export async function GET(request: NextRequest) {
  const appUrl = requireServerEnv("FOCUSOS_APP_URL");
  const user = await getServerUser();
  if (!user) {
    return NextResponse.redirect(new URL("/?authError=required", appUrl));
  }

  try {
    const state = createGoogleOAuthState(user.id);
    const authorizationUrl = googleAuthorizationUrl({
      clientId: requireServerEnv("FOCUSOS_GOOGLE_CLIENT_ID"),
      redirectUri: googleRedirectUri(appUrl),
      state: state.state,
      codeChallenge: state.codeChallenge,
    });
    const response = NextResponse.redirect(authorizationUrl);
    response.cookies.set(GOOGLE_STATE_COOKIE, state.cookieValue, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/api/integrations/google/callback",
      maxAge: GOOGLE_STATE_TTL_SECONDS,
    });
    response.headers.set("Cache-Control", "no-store");
    response.headers.set("Referrer-Policy", "no-referrer");
    return response;
  } catch {
    return NextResponse.redirect(new URL("/settings/connections?google=unavailable", appUrl));
  }
}
