import { redirect } from "next/navigation";
import { getServerUser } from "@/server/auth/session";

export const dynamic = "force-dynamic";

const messages: Record<string, string> = {
  consent_returned:
    "Google returned from the consent screen. Tokens are not connected until the next setup step.",
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

  return (
    <main className="settings-page">
      <a href="/settings">Back to settings</a>
      <h1>Google connections</h1>
      <p>Connect Gmail and your primary Google Calendar for read-only access.</p>
      {message ? <p role="status">{message}</p> : null}
      <p>
        The first consent asks to read Gmail messages and events on calendars you own.
        Calendar write access will be requested separately when scheduling is enabled.
      </p>
      <p>No message or event is imported at this stage.</p>
      <a href="/api/integrations/google/start">Continue with Google</a>
    </main>
  );
}
