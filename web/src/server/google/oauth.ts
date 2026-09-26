import "server-only";
import { createCipheriv, createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { requireServerEnv } from "@/server/env";

export const GOOGLE_STATE_COOKIE = "focusos_google_oauth_state";
export const GOOGLE_STATE_TTL_SECONDS = 600;
export const GOOGLE_READ_SCOPES = [
  "openid",
  "email",
  "profile",
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/calendar.events.owned.readonly",
] as const;
export const GOOGLE_CALENDAR_WRITE_SCOPE =
  "https://www.googleapis.com/auth/calendar.events.owned";
export const GOOGLE_CALENDAR_UPGRADE_SCOPES = [
  "openid",
  "email",
  "profile",
  GOOGLE_CALENDAR_WRITE_SCOPE,
] as const;
export type GoogleOAuthFlow = "connect" | "calendar_write";

type OAuthStatePayload = {
  version: 1;
  userId: string;
  state: string;
  codeVerifier: string;
  flow: GoogleOAuthFlow;
  issuedAt: number;
};

export function createGoogleOAuthState(userId: string, now = Date.now(), flow: GoogleOAuthFlow = "connect") {
  const state = randomBytes(32).toString("base64url");
  const codeVerifier = randomBytes(32).toString("base64url");
  const payload: OAuthStatePayload = {
    version: 1,
    userId,
    state,
    codeVerifier,
    flow,
    issuedAt: now,
  };
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", stateEncryptionKey(), iv);
  cipher.setAAD(Buffer.from("focusos-google-oauth-state-v1"));
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  const cookieValue = [iv, ciphertext, cipher.getAuthTag()]
    .map((part) => part.toString("base64url"))
    .join(".");

  return {
    state,
    codeVerifier,
    codeChallenge: createHash("sha256").update(codeVerifier).digest("base64url"),
    cookieValue,
  };
}

export function readGoogleOAuthContext(
  cookieValue: string | undefined,
  expectedState: string | null,
  userId: string | null,
  now = Date.now(),
): { codeVerifier: string; flow: GoogleOAuthFlow } | null {
  if (!cookieValue || cookieValue.length > 4096 || !expectedState || !userId) return null;
  const parts = cookieValue.split(".");
  if (parts.length !== 3) return null;

  let payload: OAuthStatePayload;
  try {
    const [iv, ciphertext, authTag] = parts.map((part) => Buffer.from(part, "base64url"));
    if (iv.length !== 12 || authTag.length !== 16 || ciphertext.length > 2048) return null;
    const decipher = createDecipheriv("aes-256-gcm", stateEncryptionKey(), iv);
    decipher.setAAD(Buffer.from("focusos-google-oauth-state-v1"));
    decipher.setAuthTag(authTag);
    const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    const decoded = JSON.parse(plaintext.toString("utf8"));
    if (!isOAuthStatePayload(decoded)) return null;
    payload = decoded;
  } catch {
    return null;
  }

  const stateA = Buffer.from(payload.state);
  const stateB = Buffer.from(expectedState);
  if (stateA.length !== stateB.length || !timingSafeEqual(stateA, stateB)) return null;
  if (payload.userId !== userId) return null;
  if (payload.issuedAt > now + 30_000) return null;
  if (now - payload.issuedAt > GOOGLE_STATE_TTL_SECONDS * 1000) return null;
  return { codeVerifier: payload.codeVerifier, flow: payload.flow };
}

export function readGoogleOAuthCodeVerifier(
  cookieValue: string | undefined,
  expectedState: string | null,
  userId: string | null,
  now = Date.now(),
): string | null {
  return readGoogleOAuthContext(cookieValue, expectedState, userId, now)?.codeVerifier ?? null;
}

export function verifyGoogleOAuthState(
  cookieValue: string | undefined,
  expectedState: string | null,
  userId: string | null,
  now = Date.now(),
): boolean {
  return readGoogleOAuthCodeVerifier(cookieValue, expectedState, userId, now) !== null;
}

function stateEncryptionKey(): Buffer {
  return createHmac("sha256", stateSigningKey())
    .update("focusos-google-oauth-state-aes256gcm-v1")
    .digest();
}

function stateSigningKey(): Buffer {
  const encoded = requireServerEnv("FOCUSOS_GOOGLE_STATE_SECRET").trim();
  const key = Buffer.from(encoded, "base64");
  if (key.length !== 32 || key.toString("base64") !== encoded) {
    throw new Error("Google OAuth state key configuration is invalid.");
  }
  return key;
}

function isOAuthStatePayload(value: unknown): value is OAuthStatePayload {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  return (
    payload.version === 1 &&
    typeof payload.userId === "string" &&
    /^[0-9a-f-]{36}$/i.test(payload.userId) &&
    typeof payload.state === "string" &&
    /^[A-Za-z0-9_-]{43}$/.test(payload.state) &&
    typeof payload.codeVerifier === "string" &&
    /^[A-Za-z0-9_-]{43}$/.test(payload.codeVerifier) &&
    (payload.flow === "connect" || payload.flow === "calendar_write") &&
    typeof payload.issuedAt === "number" &&
    Number.isSafeInteger(payload.issuedAt)
  );
}

export function googleRedirectUri(appUrl: string): string {
  const url = new URL(appUrl);
  const localHttp = url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname);
  if (url.protocol !== "https:" && !localHttp) {
    throw new Error("Google OAuth requires a secure application origin.");
  }
  return new URL("/api/integrations/google/callback", url.origin).toString();
}

export function googleAuthorizationUrl(options: {
  clientId: string;
  redirectUri: string;
  state: string;
  codeChallenge: string;
  scopes?: readonly string[];
}): string {
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", options.clientId);
  url.searchParams.set("redirect_uri", options.redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", (options.scopes ?? GOOGLE_READ_SCOPES).join(" "));
  url.searchParams.set("state", options.state);
  url.searchParams.set("code_challenge", options.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("include_granted_scopes", "true");
  url.searchParams.set("prompt", "consent");
  return url.toString();
}
