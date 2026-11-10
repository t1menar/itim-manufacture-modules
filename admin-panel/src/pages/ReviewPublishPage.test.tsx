import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { ReviewPublishPage } from "./ReviewPublishPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

const pending = {
  pending_rejects: [
    { run_id: "11111111-0000-4000-8000-000000000001", chat_id: 42, admin_user_id: 7, created_at: "2026-11-10T02:00:00Z" },
  ],
  active_cards: [
    {
      id: "22222222-0000-4000-8000-000000000002",
      run_id: "11111111-0000-4000-8000-000000000001",
      variant_id: "33333333-0000-4000-8000-000000000003",
      version: 2,
      chat_id: 42,
      created_at: "2026-11-10T02:01:00Z",
    },
  ],
};

const runs = {
  items: [
    {
      id: "44444444-0000-4000-8000-000000000004",
      job_id: "55555555-0000-4000-8000-000000000005",
      status: "succeeded",
      round: 1,
      mode: "create",
      created_at: "2026-11-10T01:00:00Z",
      finished_at: "2026-11-10T01:10:00Z",
    },
  ],
};

const intents = {
  items: [
    {
      id: "66666666-0000-4000-8000-000000000006",
      status: "published",
      generation: 3,
      url: "https://www.instagram.com/p/demo/",
      published_at: "2026-11-10T01:20:00Z",
      account: { handle: "itim", platform: "instagram", has_token: true },
    },
  ],
};

const overview = {
  modules: [{ id: "publish-instagram", name: "Publish (Instagram Graph API, fake)", stage_id: "publish", health: "up" }],
};

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.includes("/api/v1/review/pending")) return jsonResponse(pending);
      if (url.includes("/api/v1/review/runs")) return jsonResponse(runs);
      if (url.includes("/api/v1/publish/intents")) return jsonResponse(intents);
      if (url.includes("/api/v1/overview")) return jsonResponse(overview);
      return jsonResponse({ title: "not found" }, 404);
    }),
  );
}

describe("ReviewPublishPage", () => {
  it("shows pending queue, runs, intents, permalink and instagram mode", async () => {
    stubApi();
    const user = userEvent.setup();
    renderWithProviders(<ReviewPublishPage />);
    await waitFor(() => {
      expect(screen.getByText("Ожидают причину отклонения")).toBeInTheDocument();
    });
    expect(screen.getAllByText("42").length).toBeGreaterThan(0);
    expect(screen.getByText("Активные карточки")).toBeInTheDocument();
    expect(screen.getByText("fake")).toBeInTheDocument();
    expect(screen.getByText(/Publish \(Instagram Graph API, fake\)/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Прогоны/ }));
    expect(await screen.findByText("успех")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Интенты/ }));
    expect(await screen.findByText("@itim")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "ссылка" });
    expect(link).toHaveAttribute("href", "https://www.instagram.com/p/demo/");
    expect(screen.getByRole("button", { name: "Повторить публикацию" })).toBeEnabled();
  });

  it("requires a reason before republish", async () => {
    stubApi();
    const user = userEvent.setup();
    renderWithProviders(<ReviewPublishPage />);
    await user.click(await screen.findByRole("tab", { name: /Интенты/ }));
    await user.click(await screen.findByRole("button", { name: "Повторить публикацию" }));
    expect(await screen.findByText(/обязательную причину/)).toBeInTheDocument();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Повторить публикацию" })).toBeDisabled();
  });
});
