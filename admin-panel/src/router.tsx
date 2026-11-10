import { createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";

import { AppLayout } from "./components/AppLayout";
import { StubPage } from "./components/StubPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ProductionDetailPage } from "./pages/ProductionDetailPage";
import { ProductionsPage } from "./pages/ProductionsPage";
import { ReviewPublishPage } from "./pages/ReviewPublishPage";
import { AccountsPage } from "./pages/AccountsPage";

const rootRoute = createRootRoute({
  component: AppLayout,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: OverviewPage,
});

const ideasRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/ideas",
  component: () => (
    <StubPage title="Идеи и темы" hint="CRUD идей и тем пойдёт через контракт module-video, который проксирует admin-api." />
  ),
});

const productionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/productions",
  component: ProductionsPage,
});

const productionDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/productions/$id",
  component: ProductionDetailPage,
});

const reviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/review",
  component: ReviewPublishPage,
});

const accountsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/accounts",
  component: AccountsPage,
});

const promptsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/prompts",
  component: () => <StubPage title="Промпты" hint="Редактор шагов module-video." />,
});

const auditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/audit",
  component: () => <StubPage title="Журнал" hint="Журнал действий админа из базы admin-api." />,
});

const notFoundRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/404",
  component: () => <StubPage title="Страница не найдена" />,
});

const catchAllRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/$",
  beforeLoad: () => {
    throw redirect({ to: "/404" });
  },
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  ideasRoute,
  productionsRoute,
  productionDetailRoute,
  reviewRoute,
  accountsRoute,
  promptsRoute,
  auditRoute,
  notFoundRoute,
  catchAllRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
