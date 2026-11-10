import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";

import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ProblemError } from "./api/problem";
import { router } from "./router";
import { COLOR_SCHEME_KEY, theme } from "./theme/theme";
import { showProblem } from "./lib/toasts";

function readScheme(): "light" | "dark" {
  try {
    const v = localStorage.getItem(COLOR_SCHEME_KEY);
    if (v === "light" || v === "dark") {
      return v;
    }
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.meta && query.meta.silent) {
        return;
      }
      showProblem(error instanceof ProblemError ? error.problem : { title: error.message });
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 1,
    },
  },
});

const el = document.getElementById("root");
if (!el) {
  throw new Error("root element missing");
}

createRoot(el).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme={readScheme()}>
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);

