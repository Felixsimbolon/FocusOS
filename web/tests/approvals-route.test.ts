import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { GET, POST } from "../src/app/api/approvals/[[...path]]/route";
vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));
const id="123e4567-e89b-42d3-a456-426614174000";
const context=(path?:string[])=>({params:Promise.resolve({path})});
describe("approval proxy",()=>{
  beforeEach(()=>{vi.clearAllMocks();vi.mocked(getServerAccessToken).mockResolvedValue("session");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch",vi.fn().mockImplementation(async()=>Response.json([])));});
  it("rejects anonymous access and unsupported paths",async()=>{
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await GET(new NextRequest(`http://localhost/api/approvals?run_id=${id}`),context())).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
    vi.mocked(getServerAccessToken).mockResolvedValue("session");
    expect((await POST(new NextRequest("http://localhost/api/approvals/bad/decision",{method:"POST"}),context(["bad","decision"]))).status).toBe(404);
  });
  it("forwards only a bounded decision and hides upstream details",async()=>{
    expect((await POST(new NextRequest(`http://localhost/api/approvals/${id}/decision`,{method:"POST",body:'{"decision":"approve"}'}),context([id,"decision"]))).status).toBe(200);
    vi.mocked(fetch).mockResolvedValue(Response.json({detail:"private payload"},{status:409}));
    const result=await GET(new NextRequest(`http://localhost/api/approvals?run_id=${id}`),context());
    expect(result.status).toBe(409); expect(await result.text()).not.toContain("private payload");
  });
});
