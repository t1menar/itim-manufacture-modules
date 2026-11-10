import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { PromptsPage } from "./PromptsPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

const steps = [
  { step: "script", versions: ["1.0.0", "1.1.0"], default: "1.0.0", revision: 1, sha256: { "1.0.0": "aaa", "1.1.0": "bbb" } },
];

describe("PromptsPage", () => {
  it("lists steps, shows version text and audit", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input instanceof Request ? input.url : input);
        if (url.includes("/api/v1/video/prompts/audit")) return jsonResponse([{ at: "2026-11-10T02:00:00Z", actor: "seed", action: "create", step: "script", version: "1.0.0" }]);
        if (url.includes("/api/v1/video/prompts/script/1.0.0")) {
          return jsonResponse({ step: "script", version: "1.0.0", claude_md: "Hello prompt", task_md: "Do the task", created_by: "seed" });
        }
        if (url.endsWith("/api/v1/video/prompts") || url.includes("/api/v1/video/prompts?")) return jsonResponse(steps);
        return jsonResponse({ title: "not found" }, 404);
      }),
    );
    renderWithProviders(<PromptsPage />);
    await waitFor(() => {
      expect(screen.getByText(/script · активна 1.0.0/)).toBeInTheDocument();
    });
    expect(await screen.findByText("Hello prompt")).toBeInTheDocument();
    expect(screen.getByText("Do the task")).toBeInTheDocument();
    expect(screen.getByText("Аудит промптов")).toBeInTheDocument();
    expect(screen.getByText("seed")).toBeInTheDocument();
  });

  it("opens the create-version form", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input instanceof Request ? input.url : input);
        if (url.includes("/audit")) return jsonResponse([]);
        if (url.includes("/script/1.0.0")) return jsonResponse({ version: "1.0.0", claude_md: "A", task_md: "" });
        return jsonResponse(steps);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PromptsPage />);
    await user.click(await screen.findByRole("button", { name: "Новая версия" }));
    expect(await screen.findByLabelText("claude.md")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать" })).toBeDisabled();
  });
});
