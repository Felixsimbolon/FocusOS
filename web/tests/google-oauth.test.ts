import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  createGoogleOAuthState,
  GOOGLE_READ_SCOPES,
  googleAuthorizationUrl,
  googleRedirectUri,
  GOOGLE_CALENDAR_UPGRADE_SCOPES,
  readGoogleOAuthContext,
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

  it("requests only the Calendar write upgrade while retaining already granted scopes", () => {
    const url = new URL(googleAuthorizationUrl({
      clientId: "client-id", redirectUri: "https://focusos.example/api/integrations/google/callback",
      state: "upgrade-state", codeChallenge: "challenge", scopes: GOOGLE_CALENDAR_UPGRADE_SCOPES,
    }));
    expect(url.searchParams.get("scope")?.split(" ")).toEqual([...GOOGLE_CALENDAR_UPGRADE_SCOPES]);
    expect(url.searchParams.get("scope")).not.toContain("gmail.readonly");
    expect(url.searchParams.get("include_granted_scopes")).toBe("true");
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
    const upgradeState = createGoogleOAuthState("a4e0ce3a-c955-4b30-9d67-f47859cd38af", now, "calendar_write");
    expect(readGoogleOAuthContext(upgradeState.cookieValue, upgradeState.state, "a4e0ce3a-c955-4b30-9d67-f47859cd38af", now)?.flow).toBe("calendar_write");
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

  it("starts a signed-in write-scope upgrade and stores its purpose in protected state", async () => {
    vi.mocked(getServerUser).mockResolvedValue({ id: "a4e0ce3a-c955-4b30-9d67-f47859cd38af", email: null });
    vi.stubEnv("FOCUSOS_APP_URL", "http://localhost:3000");
    vi.stubEnv("FOCUSOS_GOOGLE_CLIENT_ID", "client-id");
    const { GET } = await import("../src/app/api/integrations/google/calendar-write/start/route");
    const response = await GET(new NextRequest("http://localhost:3000/api/integrations/google/calendar-write/start"));
    const authorizationUrl = new URL(response.headers.get("location")!);
    expect(authorizationUrl.searchParams.get("scope")?.split(" ")).toEqual([...GOOGLE_CALENDAR_UPGRADE_SCOPES]);
    const cookie = response.cookies.get("focusos_google_oauth_state")?.value;
    expect(readGoogleOAuthContext(cookie, authorizationUrl.searchParams.get("state"), "a4e0ce3a-c955-4b30-9d67-f47859cd38af")?.flow).toBe("calendar_write");
  });

  it("sends the write upgrade callback to its dedicated FastAPI endpoint", async () => {
    const userId = "a4e0ce3a-c955-4b30-9d67-f47859cd38af";
    vi.mocked(getServerUser).mockResolvedValue({ id: userId, email: null });
    vi.mocked(getServerAccessToken).mockResolvedValue("supabase-session-token");
    vi.stubEnv("FOCUSOS_API_URL", "http://127.0.0.1:8000");
    vi.stubEnv("FOCUSOS_APP_URL", "http://localhost:3000");
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const state = createGoogleOAuthState(userId, Date.now(), "calendar_write");
    const url = new URL("http://localhost:3000/api/integrations/google/callback");
    url.searchParams.set("state", state.state);
    url.searchParams.set("code", "calendar-upgrade-code");
    const request = new NextRequest(url, { headers: { cookie: "focusos_google_oauth_state=" + state.cookieValue } });
    const { GET } = await import("../src/app/api/integrations/google/callback/route");
    const response = await GET(request);
    expect(response.headers.get("location")).toContain("google=calendar_write_granted");
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/connections/google/calendar-write/authorize",
      expect.objectContaining({ method: "POST" }),
    );
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


describe("Gmail diagnostic proxy", () => {
  it("requires an authenticated FocusOS session", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    const { GET } = await import("../src/app/api/integrations/google/gmail/messages/[messageId]/route");
    const response = await GET(
      new NextRequest("http://localhost:3000/api/integrations/google/gmail/messages/msg-123"),
      { params: Promise.resolve({ messageId: "msg-123" }) },
    );
    expect(response.status).toBe(401);
  });

  it("proxies only safe message diagnostics and never exposes message body", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue("supabase-session-token");
    vi.stubEnv("FOCUSOS_API_URL", "http://127.0.0.1:8000");
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      message_id: "msg-123", internal_date_ms: 1799990000000, label_count: 2, text_body_bytes: 21,
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const { GET } = await import("../src/app/api/integrations/google/gmail/messages/[messageId]/route");
    const response = await GET(
      new NextRequest("http://localhost:3000/api/integrations/google/gmail/messages/msg-123"),
      { params: Promise.resolve({ messageId: "msg-123" }) },
    );
    const payload = await response.json();
    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/connections/google/gmail/messages/msg-123",
      expect.objectContaining({ headers: { Authorization: "Bearer supabase-session-token" }, cache: "no-store" }),
    );
    expect(payload).toHaveProperty("text_body_bytes", 21);
    expect(payload).not.toHaveProperty("body");
    expect(payload).not.toHaveProperty("snippet");
  });
});


describe("Calendar diagnostic proxy", () => {
  it("returns only the bounded-page summary from FastAPI", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue("supabase-session-token");
    vi.stubEnv("FOCUSOS_API_URL", "http://127.0.0.1:8000");
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      calendar: "primary", window_start: "2026-09-26T00:00:00Z", window_end: "2026-10-03T00:00:00Z",
      event_count: 2, page_has_more: false,
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const { GET } = await import("../src/app/api/integrations/google/calendar/probe/route");
    const response = await GET();
    const payload = await response.json();
    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/connections/google/calendar/probe",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(payload).toHaveProperty("event_count", 2);
    expect(payload).not.toHaveProperty("events");
  });
});
