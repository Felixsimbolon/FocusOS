import { redirect } from "next/navigation";
export default async function Settings({ searchParams }: { searchParams: Promise<{ saved?: string; error?: string }> }) {
  const params = await searchParams;
  const query = new URLSearchParams();
  if (params.saved) query.set("saved", params.saved);
  if (params.error) query.set("error", params.error);
  redirect(`/${query.size ? "?" + query : ""}#preferences`);
}
