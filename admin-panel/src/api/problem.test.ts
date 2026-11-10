import { describe, expect, it } from "vitest";

import { formatProblem, parseProblem, ProblemError } from "./problem";

describe("parseProblem", () => {
  it("reads RFC 9457 fields and code/upstream", () => {
    const p = parseProblem(
      {
        type: "about:blank",
        title: "Upstream unavailable",
        status: 503,
        detail: "module-video is down",
        code: "upstream_unavailable",
        request_id: "abc",
        upstream: "video",
      },
      503,
    );
    expect(p.code).toBe("upstream_unavailable");
    expect(p.upstream).toBe("video");
    expect(p.request_id).toBe("abc");
    expect(formatProblem(p)).toContain("module-video is down");
    expect(formatProblem(p)).toContain("video");
  });

  it("falls back when the body is not a problem", () => {
    const p = parseProblem("oops", 500);
    expect(p.status).toBe(500);
    expect(p.title).toBe("Некорректный ответ сервера");
    expect(p.detail).toBe("oops");
  });

  it("uses the HTTP status when the document has none", () => {
    const p = parseProblem({ title: "Forbidden", code: "forbidden_host" }, 403);
    expect(p.status).toBe(403);
    expect(new ProblemError(p).message).toContain("Forbidden");
  });
});
