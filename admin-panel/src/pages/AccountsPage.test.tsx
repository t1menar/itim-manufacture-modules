import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { AccountsPage } from "./AccountsPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const DUMMY_TOKEN = "dummy-ig-token-not-a-real-secret";

function stubApi(extra?: Partial<Record<string, unknown>>) {
  const bodies: Record<string, unknown> = {
    "/api/v1/publish/accounts": {
      accounts: [
        {
          id: "acc-1",
          channel_id: "itim",
          platform: "instagram",
          handle: "@itim",
          external_id: null,
          enabled: true,
          has_token: false,
          updated_at: "2026-11-10T02:00:00Z",
        },
      ],
    },
    "/api/v1/publish/secrets": {
      items: [{ key: "demo.seed_key", present: true, updated_at: "2026-11-10T02:00:00Z" }],
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
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input instanceof Request ? input.url : input);
      const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
      if (method !== "GET") {
        return jsonResponse({}, method === "POST" ? 201 : 204);
      }
      for (const [k, v] of Object.entries(bodies)) {
        if (url.includes(k)) return jsonResponse(v);
      }
      return jsonResponse({ title: "not found" }, 404);
    }),
  );
}

describe("AccountsPage", () => {
  it("lists accounts and set/not-set status, never a secret value, and shows instagram mode", async () => {
    stubApi();
    renderWithProviders(<AccountsPage />);
    await waitFor(() => {
      expect(screen.getByText("@itim")).toBeInTheDocument();
    });
    expect(screen.getAllByText("не задан").length).toBeGreaterThan(0);
    expect(screen.getAllByText("задан").length).toBeGreaterThan(0);
    expect(screen.getByText("demo.seed_key")).toBeInTheDocument();
    expect(screen.getByText("telegram.bot_token")).toBeInTheDocument();
    expect(screen.getByText("instagram.default_access_token")).toBeInTheDocument();
    expect(screen.getAllByText("s3.access_key").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/••••/)).not.toBeInTheDocument();
    expect(screen.queryByText(/символов/)).not.toBeInTheDocument();
    expect(screen.queryByText(/seed-not-a-real/)).not.toBeInTheDocument();
    expect(screen.queryByText(DUMMY_TOKEN)).not.toBeInTheDocument();
    expect(screen.getByText("fake")).toBeInTheDocument();
    expect(screen.getByText(/перезапуск module-review/)).toBeInTheDocument();
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

  it("creates an account with a write-only token and never renders the dummy value", async () => {
    stubApi();
    const user = userEvent.setup();
    renderWithProviders(<AccountsPage />);
    await screen.findByText("@itim");
    const addButtons = screen.getAllByRole("button", { name: "Добавить аккаунт" });
    const addBtn = addButtons[0];
    if (!addBtn) throw new Error("missing add button");
    await user.click(addBtn);
    await user.type(await screen.findByLabelText("Handle"), "@dummy-handle");
    await user.type(screen.getByLabelText("external_id"), "ig-user-dummy");
    const tokenField = screen.getByLabelText(/Токен доступа/);
    expect(tokenField).toHaveAttribute("type", "password");
    await user.type(tokenField, DUMMY_TOKEN);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls;
      const posted = calls.some(([input, init]) => {
        const url = String(input instanceof Request ? input.url : input);
        const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
        return method === "POST" && url.includes("/api/v1/publish/accounts");
      });
      expect(posted).toBe(true);
    });
    expect(screen.queryByDisplayValue(DUMMY_TOKEN)).not.toBeInTheDocument();
    expect(screen.queryByText(DUMMY_TOKEN)).not.toBeInTheDocument();
  });
});
