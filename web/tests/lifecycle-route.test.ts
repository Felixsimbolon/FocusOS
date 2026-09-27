import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { getServerAccessToken } from "../src/server/auth/session";
import { requireServerEnv } from "../src/server/env";
import { DELETE as disconnect } from "../src/app/api/connections/google/route";
import { DELETE as deleteSource } from "../src/app/api/sources/[[...path]]/route";

vi.mock("server-only", () => ({}));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken: vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv: vi.fn() }));
const id="123e4567-e89b-42d3-a456-426614174000";

describe("lifecycle proxies",()=>{
  beforeEach(()=>{
    vi.clearAllMocks();
    vi.mocked(getServerAccessToken).mockResolvedValue("session");
    vi.mocked(requireServerEnv).mockReturnValue("https://api.example.test");
    vi.stubGlobal("fetch",vi.fn().mockImplementation(async()=>Response.json({deleted:true,disconnected:true})));
  });
  it("rejects anonymous disconnect and deletion",async()=>{
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await disconnect()).status).toBe(401);
    expect((await deleteSource(new NextRequest(`http://localhost/api/sources/${id}`,{method:"DELETE"}),
      {params:Promise.resolve({path:[id]})})).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("allows only a UUID selected source and forwards no body",async()=>{
    expect((await deleteSource(new NextRequest("http://localhost/api/sources/all",{method:"DELETE"}),
      {params:Promise.resolve({path:["all"]})})).status).toBe(404);
    expect((await deleteSource(new NextRequest(`http://localhost/api/sources/${id}`,{method:"DELETE"}),
      {params:Promise.resolve({path:[id]})})).status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(expect.any(URL),expect.objectContaining({method:"DELETE",body:undefined}));
  });
  it("disconnects with the session token and hides upstream details",async()=>{
    expect((await disconnect()).status).toBe(200);
    vi.mocked(fetch).mockResolvedValue(Response.json({detail:"private"},{status:500}));
    const response=await disconnect();
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("private");
  });
});
