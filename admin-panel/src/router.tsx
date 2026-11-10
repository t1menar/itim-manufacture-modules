import { createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";

import { AppLayout } from "./components/AppLayout";
import { StubPage } from "./components/StubPage";
import { OverviewPage } from "./pages/OverviewPage";

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
  component: () => <StubPage title="Productions" hint="Список производств, джобы, retry / skip / cancel." />,
});

const reviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/review",
  component: () => <StubPage title="Ревью и публикации" hint="Интенты, повторная публикация с обязательной причиной." />,
});

const accountsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/accounts",
  component: () => <StubPage title="Аккаунты и креды" hint="Запись секрета разрешена, чтение — только маска и наличие." />,
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
