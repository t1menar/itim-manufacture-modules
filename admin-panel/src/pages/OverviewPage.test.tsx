import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OverviewPage } from "./OverviewPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <OverviewPage />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("OverviewPage", () => {
  it("renders modules from overview", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            productions: { done: 2 },
            jobs: {},
            variants: {},
            outbox_pending: 1,
            modules: [
              {
                id: "video-claude",
                name: "Video",
                stage_id: "video",
                health: "up",
                active: true,
                endpoint: "http://module-video:8080",
                last_seen_at: "2026-11-10T02:00:00Z",
              },
            ],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Video")).toBeInTheDocument();
    });
    expect(screen.getByText("video-claude")).toBeInTheDocument();
    expect(screen.getByText("в сети")).toBeInTheDocument();
    expect(screen.getByText("http://module-video:8080")).toBeInTheDocument();
  });

  it("shows a problem+json error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ title: "Host is not allowed", status: 403, code: "forbidden_host" }), {
          status: 403,
          statusText: "Forbidden",
          headers: { "content-type": "application/problem+json" },
        }),
      ),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Host is not allowed/)).toBeInTheDocument();
    });
  });
});
