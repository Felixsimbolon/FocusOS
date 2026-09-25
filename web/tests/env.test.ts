import { afterEach, describe, expect, it, vi } from "vitest";

import { requireServerEnv } from "../src/server/env";

const name = "FOCUSOS_TEST_SECRET";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("requireServerEnv", () => {
  it("names a missing variable without logging a value", () => {
    vi.stubEnv(name, undefined);

    expect(() => requireServerEnv(name)).toThrowError(
      `Missing required environment variable: ${name}`,
    );
  });

  it("returns a configured server value", () => {
    vi.stubEnv(name, "sample-value");

    expect(requireServerEnv(name)).toBe("sample-value");
  });
});
