import { redirect } from "next/navigation";
import { getServerAccessToken, getServerUser } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
import { GmailMessageProbe } from "./gmail-message-probe";
import { CalendarPageProbe } from "./calendar-page-probe";
import { DisconnectGoogle } from "./disconnect-google";

export const dynamic = "force-dynamic";

const messages: Record<string, string> = {
  connected: "Google is connected. Granted access is shown below.",
  calendar_write_granted: "Google Calendar write permission is enabled. Planning submissions can now create focus events automatically.",
  exchange_failed: "Google consent returned, but FocusOS could not complete the secure connection. Try again.",
  callback_not_allowed: "The API does not allow this Google callback URL. Check FOCUSOS_GOOGLE_REDIRECT_URIS in the API process.",
  code_rejected: "Google rejected the authorization code. Check that the API client ID and secret belong to the same OAuth Web client used by the web app, then reconnect.",
  permissions_incomplete: "Google did not grant all requested Gmail and Calendar read permissions. Reconnect and approve both.",
  offline_access_missing: "Google did not issue offline access. Reconnect and approve the requested access.",
  api_config_missing: "The API is missing its Google OAuth client ID, secret, or allowed callback URL.",
  encryption_config_missing: "The API token encryption keys are missing or invalid.",
  connection_storage_unavailable: "The API could not save the Google connection. Check its Supabase secret key and database migrations.",
  cancelled: "Google consent was cancelled. No connection was created.",
  invalid_state: "The Google authorization response was invalid or expired. Start again.",
  unavailable: "Google connection setup is not configured on this server yet.",
};

export default async function ConnectionsSettings({
  searchParams,
}: {
  searchParams: Promise<{ google?: string }>;
}) {
  const user = await getServerUser();
  if (!user) redirect("/");

  const params = await searchParams;
  const message = params.google ? messages[params.google] : undefined;
  let connection: {
    display_email: string | null;
    granted_scopes: string[];
    status: "connected" | "reconnect_required" | "disconnected";
  } | null = null;
  const accessToken = await getServerAccessToken();
  if (accessToken) {
    try {
      const apiUrl = requireServerEnv("FOCUSOS_API_URL").replace(/\/$/, "");
      const result = await fetch(apiUrl + "/connections/google", {
        headers: { Authorization: "Bearer " + accessToken },
        cache: "no-store",
      });
      if (result.ok) {
        const body = await result.json();
        connection = body.connection;
      }
    } catch {
      connection = null;
    }
  }

  return (
    <main className="settings-page">
      <a href="/#preferences">Back to Today</a>
      <h1>Google connections</h1>
      <p>Connect Gmail and your primary Google Calendar for read-only access.</p>
      {message ? <p role="status">{message}</p> : null}
      <p>
        The first consent asks to read Gmail messages and events on calendars you own.
        Calendar write access will be requested separately when scheduling is enabled.
      </p>
      {connection?.status === "connected" ? (
        <section aria-label="Google connection status">
          <h2>Connected</h2>
          {connection.display_email ? <p>{connection.display_email}</p> : null}
          <ul>
            {connection.granted_scopes.includes("https://www.googleapis.com/auth/gmail.readonly") ? <li>Gmail read access</li> : null}
            {connection.granted_scopes.includes("https://www.googleapis.com/auth/calendar.events.owned.readonly") ? <li>Read events on calendars you own</li> : null}
            {connection.granted_scopes.includes("https://www.googleapis.com/auth/calendar.events.owned") ? <li>Calendar event write access (Planning submissions can create events automatically; you can cancel FocusOS blocks from Home)</li> : null}
          </ul>
          {!connection.granted_scopes.includes("https://www.googleapis.com/auth/calendar.events.owned") ? (
            <p><a className="control-button" href="/api/integrations/google/calendar-write/start">Enable Calendar event writes</a></p>
          ) : null}
          <GmailMessageProbe />
          <CalendarPageProbe />
          <DisconnectGoogle />
        </section>
      ) : connection?.status === "disconnected" ? (
        <p role="status">Google is disconnected. Saved tokens were removed; reconnect to resume sync.</p>
      ) : connection?.status === "reconnect_required" ? (
        <p role="status">Google needs to be connected or reauthorized.</p>
      ) : null}
      <p>No message or event is imported at this stage.</p>
      <a className="control-button" href="/api/integrations/google/start">{connection?.status === "connected" ? "Reconnect Google" : "Continue with Google"}</a>
    </main>
  );
}
