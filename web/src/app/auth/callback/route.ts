import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const code = new URL(request.url).searchParams.get("code");

  if (!code) {
    return NextResponse.redirect(new URL("/?authError=callback", request.url));
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    return NextResponse.redirect(new URL("/?authError=callback", request.url));
  }

  return NextResponse.redirect(new URL("/", request.url));
}
