import "server-only";
import { getServerAccessToken } from "../auth/session";
import { forward } from "../forward";

/** What Home shows first, read on the server so the page arrives with the user's data. */
export type HomeData = {
  today: { tasks: unknown[]; truncated: boolean; today?: string; timezone?: string } | null;
  open: { tasks: unknown[]; truncated: boolean } | null;
  projects: { id: string; name: string; created_at: string }[] | null;
  blocks: unknown[] | null;
};

async function read<T>(token: string, path: string): Promise<T | null> {
  try {
    const response = await forward(token, path, "GET", undefined, 6_000);
    return response.ok ? (await response.json()) as T : null;
  } catch { return null; }
}

/** Every read is optional: a slow or failed one leaves its panel to load in the browser as before. */
export async function loadHome(): Promise<HomeData> {
  const token = await getServerAccessToken();
  if (!token) return { today: null, open: null, projects: null, blocks: null };
  const [today, open, projects, blocks] = await Promise.all([
    read<HomeData["today"]>(token, "/tasks/today"),
    read<HomeData["open"]>(token, "/tasks?status=open"),
    read<{ projects: HomeData["projects"] }>(token, "/projects"),
    read<unknown[]>(token, "/product/focus-blocks"),
  ]);
  return { today, open, projects: projects?.projects ?? null, blocks: Array.isArray(blocks) ? blocks : null };
}
