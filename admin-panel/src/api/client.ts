import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./schema";
import { ProblemError, problemFromResponse } from "./problem";

const errorMiddleware: Middleware = {
  async onResponse({ response }) {
    if (response.ok) {
      return undefined;
    }
    const problem = await problemFromResponse(response);
    throw new ProblemError(problem, response.status);
  },
};

function defaultBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://127.0.0.1";
}

function currentFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return globalThis.fetch(input, init);
}

/** Same-origin client for /api/v1 (and /health). Types come from gen:api. */
export const api = createClient<paths>({ baseUrl: defaultBaseUrl(), fetch: currentFetch });
api.use(errorMiddleware);

export async function fetchHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch("/health", { signal, headers: { accept: "application/json" } });
    if (!res.ok) {
      return false;
    }
    const body: unknown = await res.json();
    return Boolean(body && typeof body === "object" && (body as { status?: string }).status === "ok");
  } catch {
    return false;
  }
}

export async function fetchOverview(signal?: AbortSignal) {
  const { data } = await api.GET("/api/v1/overview", { signal });
  if (!data) {
    throw new ProblemError({ title: "Пустой ответ overview", status: 502 }, 502);
  }
  return data;
}

export { ProblemError };
