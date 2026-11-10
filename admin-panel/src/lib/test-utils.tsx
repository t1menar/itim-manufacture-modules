import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

export function renderWithProviders(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  const client = createTestQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MantineProvider>
        <Notifications />
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </MantineProvider>
    );
  }
  return { ...render(ui, { wrapper: Wrapper, ...options }), client };
}

export function jsonResponse(body: unknown, status = 200, contentType = "application/json"): Response {
  const type = status >= 400 ? "application/problem+json" : contentType;
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}
