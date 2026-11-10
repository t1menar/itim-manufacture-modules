import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { ProductionDetailPage } from "./ProductionDetailPage";

const ID = "01900000-0000-7000-8000-0000000000aa";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...mod,
    useParams: () => ({ id: ID }),
    Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  };
});

const detail = {
  id: ID,
  idea_ref: "idea:42:v1",
  idea_rev: 1,
  run_no: 1,
  status: "running",
  language: "en",
  started_at: "2026-11-10T02:00:00Z",
  rev: 3,
  variants: [
    {
      id: "01900000-0000-7000-8000-0000000000bb",
      language: "en",
      status: "needs_attention",
      position: 1,
      channels: ["itim"],
      rev: 2,
    },
  ],
  jobs: [
    {
      id: "01900000-0000-7000-8000-0000000000cc",
      stage_id: "video",
      module_id: "video-claude",
      attempt: 1,
      status: "running",
      cancel_requested: false,
      created_at: "2026-11-10T02:00:00Z",
      updated_at: "2026-11-10T02:01:00Z",
      rev: 1,
    },
  ],
  events: [
    {
      id: 7,
      type: "job.started",
      actor: "system",
      at: "2026-11-10T02:00:05Z",
      job_id: "01900000-0000-7000-8000-0000000000cc",
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProductionDetailPage", () => {
  it("renders variants, jobs and timeline", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(detail)));
    renderWithProviders(<ProductionDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("нужно внимание")).toBeInTheDocument();
    });
    expect(screen.getByText("video-claude")).toBeInTheDocument();
    expect(screen.getByText("job.started")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Пропустить" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Отменить" })).toBeEnabled();
  });

  it("asks for a reason before skip", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(detail)));
    const user = (await import("@testing-library/user-event")).default;
    renderWithProviders(<ProductionDetailPage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Пропустить" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Пропустить" }));
    expect(await screen.findByText(/Укажите причину/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Пропустить вариант" })).toBeDisabled();
  });
});
