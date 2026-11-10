import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchHealth, fetchOverview, ProblemError } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchHealth", () => {
  it("is true when admin-api returns status ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok" }),
      }),
    );
    await expect(fetchHealth()).resolves.toBe(true);
  });

  it("is false on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(fetchHealth()).resolves.toBe(false);
  });
});

describe("fetchOverview", () => {
  it("returns the typed payload", async () => {
    const payload = {
      productions: {},
      jobs: { running: 1 },
      variants: {},
      outbox_pending: 0,
      modules: [{ id: "video-claude", name: "Video", health: "up", stage_id: "video" }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } })),
    );
    await expect(fetchOverview()).resolves.toMatchObject({ jobs: { running: 1 } });
  });

  it("throws ProblemError for problem+json", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            title: "Upstream unavailable",
            status: 503,
            code: "upstream_unavailable",
            upstream: "core",
          }),
          { status: 503, statusText: "Service Unavailable", headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );
    try {
      await fetchOverview();
      expect.fail("should throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ProblemError);
      const p = (err as ProblemError).problem;
      expect(p.code).toBe("upstream_unavailable");
      expect(p.upstream).toBe("core");
    }
  });
});
