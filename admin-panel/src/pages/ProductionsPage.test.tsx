import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderWithProviders } from "../lib/test-utils";
import { ProductionsPage } from "./ProductionsPage";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...mod,
    Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  };
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const item = {
  id: "01900000-0000-7000-8000-0000000000aa",
  idea_ref: "idea:42:v1",
  idea_rev: 1,
  run_no: 1,
  pipeline_id: "default-v1",
  status: "running",
  language: "en",
  started_at: "2026-11-10T02:00:00Z",
  rev: 3,
};

describe("ProductionsPage", () => {
  it("renders a list of productions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ items: [item], next_cursor: null })));
    renderWithProviders(<ProductionsPage />);
    await waitFor(() => {
      expect(screen.getByText("idea:42:v1")).toBeInTheDocument();
    });
    expect(screen.getByText("идёт")).toBeInTheDocument();
    expect(screen.getByText("en")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ items: [], next_cursor: null })));
    renderWithProviders(<ProductionsPage />);
    await waitFor(() => {
      expect(screen.getByText("Пока нет производств.")).toBeInTheDocument();
    });
  });
});
