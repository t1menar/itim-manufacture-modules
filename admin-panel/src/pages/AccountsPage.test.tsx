import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { AccountsPage } from "./AccountsPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubApi(extra?: Partial<Record<string, unknown>>) {
  const bodies: Record<string, unknown> = {
    "/api/v1/publish/accounts": {
      accounts: [{ id: "acc-1", channel_id: "itim", platform: "instagram", handle: "@itim", enabled: true, has_token: false }],
    },
    "/api/v1/publish/secrets": {
      items: [{ key: "demo.seed_key", present: true, length: 24, updated_at: "2026-11-10T02:00:00Z" }],
    },
    "/api/v1/review/secrets": { items: [] },
    "/api/v1/video/credentials": [],
    "/api/v1/overview": {
      modules: [{ id: "publish-instagram", name: "Publish (Instagram Graph API, fake)", health: "up" }],
    },
    ...extra,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      for (const [k, v] of Object.entries(bodies)) {
        if (url.includes(k)) return jsonResponse(v);
      }
      return jsonResponse({ title: "not found" }, 404);
    }),
  );
}

describe("AccountsPage", () => {
  it("lists accounts and secret masks, never a secret value, and shows instagram mode", async () => {
    stubApi();
    renderWithProviders(<AccountsPage />);
    await waitFor(() => {
      expect(screen.getByText("@itim")).toBeInTheDocument();
    });
    expect(screen.getByText("нет токена")).toBeInTheDocument();
    expect(screen.getByText("demo.seed_key")).toBeInTheDocument();
    expect(screen.getByText("•••• (24 символов)")).toBeInTheDocument();
    expect(screen.queryByText(/seed-not-a-real/)).not.toBeInTheDocument();
    expect(screen.getByText("fake")).toBeInTheDocument();
    // password fields must not autocomplete
    const secretsValue = screen.getAllByLabelText("Значение")[0];
    expect(secretsValue).toHaveAttribute("type", "password");
    expect(secretsValue).toHaveAttribute("autocomplete", "off");
  });

  it("asks for a token in a password field before saving", async () => {
    stubApi();
    const user = userEvent.setup();
    renderWithProviders(<AccountsPage />);
    await user.click(await screen.findByRole("button", { name: "Задать токен" }));
    expect(await screen.findByText(/Значение не будет показано/)).toBeInTheDocument();
    const input = screen.getByLabelText("Access token");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "off");
  });
});
