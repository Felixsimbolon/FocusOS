import { redirect } from "next/navigation";
export default async function Activity({ searchParams }: { searchParams: Promise<{ source?: string }> }) {
  const { source } = await searchParams;
  redirect(source ? "/?source=" + encodeURIComponent(source) + "#sources" : "/#sources");
}
