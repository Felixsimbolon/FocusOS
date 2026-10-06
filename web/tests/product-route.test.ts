import {beforeEach,describe,expect,it,vi} from "vitest";
import {NextRequest} from "next/server";
import {GET,POST} from "../src/app/api/product/[[...path]]/route";
import {getServerAccessToken} from "../src/server/auth/session";
vi.mock("server-only",()=>({}));vi.mock("../src/server/auth/session",()=>({getServerAccessToken:vi.fn()}));vi.mock("../src/server/env",()=>({requireServerEnv:()=>"https://api.example.test"}));
const id="123e4567-e89b-42d3-a456-426614174000";
const ctx=(path:string[])=>({params:Promise.resolve({path})});
describe("product proxy",()=>{
 beforeEach(()=>{vi.clearAllMocks();vi.mocked(getServerAccessToken).mockResolvedValue("server-session");vi.stubGlobal("fetch",vi.fn().mockResolvedValue(Response.json({ok:true})));});
 it("requires auth and rejects arbitrary backend routes",async()=>{vi.mocked(getServerAccessToken).mockResolvedValue(null);expect((await GET(new NextRequest("http://localhost"),ctx(["export"]))).status).toBe(401);expect(fetch).not.toHaveBeenCalled();vi.mocked(getServerAccessToken).mockResolvedValue("session");expect((await GET(new NextRequest("http://localhost"),ctx(["internal"]))).status).toBe(404);});
 it("exports with no-store and a fixed download filename",async()=>{const r=await GET(new NextRequest("http://localhost"),ctx(["export"]));expect(r.headers.get("Content-Disposition")).toBe("attachment; filename=focusos-export.json");expect(r.headers.get("Cache-Control")).toBe("no-store");expect(await r.text()).not.toContain("server-session");});
 it("allows cancellation only by saved action ID",async()=>{expect((await POST(new NextRequest("http://localhost",{method:"POST"}),ctx(["focus-blocks",id,"cancel"]))).status).toBe(200);expect((await POST(new NextRequest("http://localhost",{method:"POST"}),ctx(["focus-blocks","evil","cancel"]))).status).toBe(404);});
 it("redacts arbitrary upstream failure details",async()=>{vi.mocked(fetch).mockResolvedValue(Response.json({detail:"private provider content"},{status:500}));const r=await GET(new NextRequest("http://localhost"),ctx(["diagnostics"]));expect(r.status).toBe(503);expect(await r.text()).not.toContain("private provider");});
});
