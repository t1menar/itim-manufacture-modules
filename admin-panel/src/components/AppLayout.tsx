import {
  ActionIcon,
  AppShell,
  Burger,
  Group,
  NavLink,
  Text,
  Title,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";

import { COLOR_SCHEME_KEY } from "../theme/theme";
import { ConnectionHeader } from "./ConnectionHeader";

const NAV = [
  { to: "/", label: "Обзор" },
  { to: "/ideas", label: "Идеи и темы" },
  { to: "/productions", label: "Productions" },
  { to: "/review", label: "Ревью и публикации" },
  { to: "/accounts", label: "Аккаунты и креды" },
  { to: "/prompts", label: "Промпты" },
  { to: "/audit", label: "Журнал" },
] as const;

export function AppLayout() {
  const [opened, { toggle }] = useDisclosure();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme("light");

  const toggleTheme = () => {
    const next = computed === "dark" ? "light" : "dark";
    setColorScheme(next);
    try {
      localStorage.setItem(COLOR_SCHEME_KEY, next);
      document.documentElement.setAttribute("data-mantine-color-scheme", next);
    } catch {
      /* ignore */
    }
  };

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 260, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group wrap="nowrap" gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={4} visibleFrom="xs">
              Manufacture
            </Title>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <ConnectionHeader />
            <Tooltip label={computed === "dark" ? "Светлая тема" : "Тёмная тема"}>
              <ActionIcon variant="subtle" onClick={toggleTheme} aria-label="Переключить тему" size="lg">
                {computed === "dark" ? "☀" : "☾"}
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="sm">
        <Text size="xs" c="dimmed" tt="uppercase" fw={600} mb="xs" px="sm">
          Разделы
        </Text>
        {NAV.map((item) => {
          const active = item.to === "/" ? pathname === "/" : pathname === item.to || pathname.startsWith(`${item.to}/`);
          return (
            <NavLink
              key={item.to}
              component={Link}
              to={item.to}
              label={item.label}
              active={active}
              onClick={() => {
                if (opened) {
                  toggle();
                }
              }}
            />
          );
        })}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
