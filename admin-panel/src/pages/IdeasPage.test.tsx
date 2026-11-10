import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { IdeasPage, NOT_SUPPORTED_MESSAGE } from "./IdeasPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function stub(status: number, ideas: unknown, topics: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.includes("/api/v1/topics")) {
        return status === 200 ? jsonResponse(topics) : jsonResponse({ title: "Not Found", status, code: "not_found" }, status);
      }
      if (url.includes("/api/v1/ideas")) {
        return status === 200 ? jsonResponse(ideas) : jsonResponse({ title: "Not Found", status, code: "not_found" }, status);
      }
      return jsonResponse({ title: "not found" }, 404);
    }),
  );
}

describe("IdeasPage", () => {
  it("shows a clear not-supported state when module-video returns 404", async () => {
    stub(404, { title: "Not Found" }, { title: "Not Found" });
    renderWithProviders(<IdeasPage />);
    expect(await screen.findByText(NOT_SUPPORTED_MESSAGE, { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/VIDEO_ADMIN_ROUTES/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Добавить идею" })).not.toBeInTheDocument();
  });

  it("lists topics and ideas when the module implements the contract", async () => {
    stub(
      200,
      { items: [{ id: 7, topic_id: 1, title: "Идея про песок", status: "draft", language: "ru", author: "seed" }] },
      { items: [{ id: 1, code: "sand", title: "Песочные истории", description: "демо", active: true }] },
    );
    renderWithProviders(<IdeasPage />);
    await waitFor(() => {
      expect(screen.getAllByText("Песочные истории").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("Идея про песок")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить идею" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "В ready" })).toBeInTheDocument();
    expect(screen.queryByText(NOT_SUPPORTED_MESSAGE)).not.toBeInTheDocument();
  });
});
