import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, after } from "next/server";
import { POST } from "../src/app/api/commands/route";
import { getServerAccessToken } from "../src/server/auth/session";
import { runBackgroundJob } from "../src/server/jobs";
vi.mock("server-only", () => ({}));
vi.mock("next/server", async original => ({ ...(await original<typeof import("next/server")>()), after:vi.fn() }));
vi.mock("../src/server/auth/session", () => ({ getServerAccessToken:vi.fn() }));
vi.mock("../src/server/env", () => ({ requireServerEnv:() => "https://api.example.test" }));
vi.mock("../src/server/jobs", () => ({ runBackgroundJob:vi.fn() }));
const id="123e4567-e89b-42d3-a456-426614174000";
const request=(data:unknown) => new NextRequest("http://localhost/api/commands", { method:"POST",body:JSON.stringify(data) });
describe("one inferred work request", () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.mocked(getServerAccessToken).mockResolvedValue("private-server-session");
    vi.stubGlobal("fetch",vi.fn().mockResolvedValue(Response.json({ run_id:id,background_job:{id,status:"queued"} })));
  });
  it("requires authentication before reading or forwarding descriptions", async () => {
    vi.mocked(getServerAccessToken).mockResolvedValue(null);
    expect((await POST(request({ text:"Reserve time",request_key:id }))).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("forwards only text and replay key; schedules durable processing after response", async () => {
    const result=await POST(request({ text:"Cari waktu besok untuk belajar Python selama 45 menit",request_key:id }));
    expect(result.status).toBe(202);
    expect(await result.text()).not.toContain("private-server-session");
    expect(fetch).toHaveBeenCalledWith("https://api.example.test/commands", expect.objectContaining({ method:"POST",headers:expect.objectContaining({ Authorization:"Bearer private-server-session" }),redirect:"error" }));
    expect(runBackgroundJob).not.toHaveBeenCalled();
    await (vi.mocked(after).mock.calls[0][0] as () => Promise<void>)();
    expect(runBackgroundJob).toHaveBeenCalledWith("private-server-session",expect.objectContaining({id}));
  });
  it.each([{text:"",request_key:id},{text:"x".repeat(1001),request_key:id},{text:"Study",request_key:"invalid"},{text:"Study",request_key:id,type:"schedule"}])("rejects invalid or client-selected action before reaching the API",async data => {
    expect((await POST(request(data))).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
    expect(after).not.toHaveBeenCalled();
  });
  it("does not leak provider/database errors or claim to start unavailable work",async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({detail:"private provider key"},{status:500}));
    const result=await POST(request({text:"Work",request_key:id}));
    expect(result.status).toBe(503); expect(await result.text()).not.toContain("private provider key"); expect(after).not.toHaveBeenCalled();
  });
});
