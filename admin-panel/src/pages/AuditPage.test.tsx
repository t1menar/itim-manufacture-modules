import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { AuditPage } from "./AuditPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AuditPage", () => {
  it("lists audit rows and sends filters, never showing secret values", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      if (!url.includes("/api/v1/audit")) {
        return jsonResponse({ title: "not found" }, 404);
      }
      const parsed = new URL(url, "http://localhost");
      const actor = parsed.searchParams.get("actor");
      const items =
        actor === "other"
          ? [{ id: 2, at: "2026-11-10T10:00:00Z", actor: "other", action: "ideas.read", outcome: "error", http_status: 500, details: {} }]
          : [
              {
                id: 3,
                at: "2026-11-10T09:00:00Z",
                actor: "local:admin",
                action: "review.secrets.write",
                resource_type: "secrets",
                resource_id: "telegram.bot_token",
                outcome: "ok",
                http_status: 204,
                details: { value: "***" },
              },
            ];
      return jsonResponse({ items, next_cursor: actor ? undefined : "2" });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<AuditPage />);
    await waitFor(() => {
      expect(screen.getByText("review.secrets.write")).toBeInTheDocument();
    });
    expect(screen.getByText("local:admin")).toBeInTheDocument();
    expect(screen.getByText("secrets:telegram.bot_token")).toBeInTheDocument();
    expect(screen.queryByText(/dummy-/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Дальше" })).toBeEnabled();

    const user = userEvent.setup();
    await user.clear(screen.getByLabelText("Актор"));
    await user.type(screen.getByLabelText("Актор"), "other");
    await user.click(screen.getByRole("button", { name: "Применить" }));
    await waitFor(() => {
      expect(screen.getByText("ideas.read")).toBeInTheDocument();
    });
    const filtered = fetchMock.mock.calls.some(([input]) => {
      const url = String(input instanceof Request ? input.url : input);
      return url.includes("actor=other");
    });
    expect(filtered).toBe(true);
    expect(screen.queryByText(/dummy-/)).not.toBeInTheDocument();
  });
});
