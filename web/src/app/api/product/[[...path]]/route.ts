import { NextRequest, NextResponse } from "next/server";
import { getServerAccessToken } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const maxDuration = 60;
type Context = { params: Promise<{ path?: string[] }> };
async function proxy(request: NextRequest, context: Context, method: "GET" | "POST") {
 const token=await getServerAccessToken();
 if (!token) return NextResponse.json({error:"Authentication required"},{status:401});
 const path=(await context.params).path || [];
 const valid=method==="GET" ? path.length===1 && ["diagnostics","history","export","focus-blocks"].includes(path[0])
   : path.length===3 && path[0]==="focus-blocks" && UUID.test(path[1]) && path[2]==="cancel";
 if (!valid) return NextResponse.json({error:"Product route not found"},{status:404});
 try {
  const r=await fetch(requireServerEnv("FOCUSOS_API_URL").replace(/\/$/,"")+"/product/"+path.join("/"),{method,headers:{Authorization:`Bearer ${token}`},cache:"no-store",redirect:"error",signal:AbortSignal.timeout(55_000)});
  if (!r.ok) return NextResponse.json({error:r.status===401?"Sign in again.":r.status===409?"This block cannot be cancelled. Check its Calendar state.":"Product data unavailable. Check server configuration and migrations."},{status:[401,409].includes(r.status)?r.status:503});
  const headers:Record<string,string>={"Cache-Control":"no-store"};
  if (path[0]==="export") headers["Content-Disposition"]="attachment; filename=focusos-export.json";
  return NextResponse.json(await r.json(),{headers});
 } catch {return NextResponse.json({error:"Product data unavailable."},{status:503});}
}
export async function GET(r:NextRequest,c:Context){return proxy(r,c,"GET");}
export async function POST(r:NextRequest,c:Context){return proxy(r,c,"POST");}
