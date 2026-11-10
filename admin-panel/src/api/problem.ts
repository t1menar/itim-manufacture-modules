/** RFC 9457 problem+json as returned by admin-api. */
export type Problem = {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  code?: string;
  request_id?: string;
  upstream?: string;
};

export class ProblemError extends Error {
  readonly problem: Problem;
  readonly status: number;

  constructor(problem: Problem, status = problem.status ?? 0) {
    super(formatProblem(problem));
    this.name = "ProblemError";
    this.problem = problem;
    this.status = status;
  }
}

export function formatProblem(p: Problem): string {
  const title = p.title?.trim() || p.code || "Ошибка запроса";
  const extra = [p.detail, p.upstream ? `источник: ${p.upstream}` : "", p.code && p.code !== title ? p.code : ""]
    .map((s) => (s ?? "").trim())
    .filter(Boolean);
  return extra.length ? `${title}: ${extra.join(" · ")}` : title;
}

export function parseProblem(body: unknown, status: number): Problem {
  if (body && typeof body === "object") {
    const o = body as Record<string, unknown>;
    const str = (k: string): string | undefined =>
      typeof o[k] === "string" && (o[k] as string).length > 0 ? (o[k] as string) : undefined;
    const num = (k: string): number | undefined => (typeof o[k] === "number" ? (o[k] as number) : undefined);
    const problem: Problem = {
      type: str("type"),
      title: str("title"),
      status: num("status") ?? status,
      detail: str("detail"),
      instance: str("instance"),
      code: str("code"),
      request_id: str("request_id"),
      upstream: str("upstream"),
    };
    if (problem.title || problem.code || problem.detail) {
      return problem;
    }
  }
  return { title: "Некорректный ответ сервера", status, detail: typeof body === "string" ? body.slice(0, 200) : undefined };
}

export async function problemFromResponse(res: Response): Promise<Problem> {
  const status = res.status;
  const ct = res.headers.get("content-type") ?? "";
  try {
    if (ct.includes("json")) {
      return parseProblem(await res.json(), status);
    }
    const text = await res.text();
    return parseProblem(text, status);
  } catch {
    return { title: res.statusText || "Ошибка сети", status };
  }
}
