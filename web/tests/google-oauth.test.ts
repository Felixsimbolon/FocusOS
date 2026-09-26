import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  createGoogleOAuthState,
  GOOGLE_READ_SCOPES,
  googleAuthorizationUrl,
  googleRedirectUri,
  verifyGoogleOAuthState,
} from "../src/server/google/oauth";
import { getServerAccessToken, getServerUser } from "../src/server/auth/session";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerUser: vi.fn(), getServerAccessToken: vi.fn() }));

const secret = Buffer.alloc(32, 7).toString("base64");

describe("Google consent configuration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("FOCUSOS_GOOGLE_STATE_SECRET", secret);
  });

  it("asks only for the selected read scopes and offline access", () => {
    const url = new URL(
      googleAuthorizationUrl({
        clientId: "client-id",
        redirectUri: "https://focusos.example/api/integrations/google/callback",
        state: "test-state",
        codeChallenge: "challenge",
      }),
    );
    expect(url.origin).toBe("https://accounts.google.com");
    expect(url.searchParams.get("access_type")).toBe("offline");
    expect(url.searchParams.get("include_granted_scopes")).toBe("true");
    expect(url.searchParams.get("scope")?.split(" ")).toEqual([...GOOGLE_READ_SCOPES]);
    expect(url.searchParams.get("scope")).not.toContain("calendar.events.owned ");
  });

  it("uses the fixed callback path and rejects insecure hosted origins", () => {
    expect(googleRedirectUri("http://localhost:3000")).toBe(
      "http://localhost:3000/api/integrations/google/callback",
    );
    expect(() => googleRedirectUri("http://example.com")).toThrow();
  });

  it("binds signed state and PKCE verifier to the current user and a short expiry", () => {
    const now = 1_800_000_000_000;
    const created = createGoogleOAuthState("a4e0ce3a-c955-4b30-9d67-f47859cd38af", now);
    expect(created.cookieValue).not.toContain(created.codeVerifier);
    expect(
      verifyGoogleOAuthState(
        created.cookieValue,
        created.state,
        "a4e0ce3a-c955-4b30-9d67-f47859cd38af",
        now + 1000,
      ),
    ).toBe(true);
    expect(
      verifyGoogleOAuthState(
        created.cookieValue,
        created.state,
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
        now + 1000,
      ),
    ).toBe(false);
    expect(verifyGoogleOAuthState(created.cookieValue, created.state, null, now)).toBe(false);
    expect(verifyGoogleOAuthState(created.cookieValue, created.state, "a4e0ce3a-c955-4b30-9d67-f47859cd38af", now + 601_000)).toBe(false);
    expect(
      verifyGoogleOAuthState(
        (created.cookieValue[0] === "A" ? "B" : "A") + created.cookieValue.slice(1),
        created.state,
        "a4e0ce3a-c955-4b30-9d67-f47859cd38af",
        now,
      ),
    ).toBe(false);
  });
});

describe("Google consent routes", () => {
  it("does not start consent without an authenticated FocusOS session", async () => {
    vi.mocked(getServerUser).mockResolvedValue(null);
    vi.stubEnv("FOCUSOS_APP_URL", "http://localhost:3000");
    const { GET } = await import("../src/app/api/integrations/google/start/route");
    const response = await GET(new NextRequest("http://localhost:3000/api/integrations/google/start"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/?authError=required");
  });

  it("binds consent state to the verified user and sets an HttpOnly callback-only cookie", async () => {
    vi.mocked(getServerUser).mockResolvedValue({
      id: "a4e0ce3a-c955-4b30-9d67-f47859cd38af",
      email: null,
    });
    vi.stubEnv("FOCUSOS_APP_URL", "http://localhost:3000");
    vi.stubEnv("FOCUSOS_GOOGLE_CLIENT_ID", "client-id");
    const { GET } = await import("../src/app/api/integrations/google/start/route");
    const response = await GET(new NextRequest("http://localhost:3000/api/integrations/google/start"));
    const authorizationUrl = new URL(response.headers.get("location")!);
    expect(authorizationUrl.origin).toBe("https://accounts.google.com");
    expect(response.headers.get("cache-control")).toBe("no-store");
    const cookie = response.cookies.get("focusos_google_oauth_state");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.path).toBe("/api/integrations/google/callback");
    expect(cookie?.sameSite).toBe("lax");
  });

  it("validates callback state, drops the one-use cookie and never forwards the code", async () => {
    const userId = "a4e0ce3a-c955-4b30-9d67-f47859cd38af";
    vi.mocked(getServerUser).mockResolvedValue({ id: userId, email: null });
    vi.mocked(getServerAccessToken).mockResolvedValue("supabase-session-token");
    vi.stubEnv("FOCUSOS_API_URL", "http://127.0.0.1:8000");
    vi.stubEnv("FOCUSOS_APP_URL", "http://localhost:3000");
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const oauth = await import("../src/server/google/oauth");
    const state = oauth.createGoogleOAuthState(userId);
    const url = new URL("http://localhost:3000/api/integrations/google/callback");
    url.searchParams.set("state", state.state);
    url.searchParams.set("code", "authorization-code-must-not-be-forwarded");
    const request = new NextRequest(url, {
      headers: { cookie: "focusos_google_oauth_state=" + state.cookieValue },
    });
    const { GET } = await import("../src/app/api/integrations/google/callback/route");
    const response = await GET(request);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/settings/connections?google=connected",
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/connections/google/authorize",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer supabase-session-token" }),
        body: expect.stringContaining("code_verifier"),
      }),
    );
    expect(response.headers.get("location")).not.toContain("authorization-code-must-not-be-forwarded");
    expect(response.cookies.get("focusos_google_oauth_state")?.maxAge).toBe(0);
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
  });
});
