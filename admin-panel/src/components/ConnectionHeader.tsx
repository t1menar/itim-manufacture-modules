import { Badge, Group, Text, Tooltip } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { fetchHealth, fetchOverview } from "../api/client";
import { ModuleHealthBadge } from "./ModuleHealthBadge";

export function ConnectionHeader() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: 10_000,
    retry: 1,
  });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: ({ signal }) => fetchOverview(signal),
    refetchInterval: 10_000,
    retry: 1,
  });

  const apiUp = health.data === true;
  const apiLabel = health.isPending ? "проверка…" : apiUp ? "admin-api: связь есть" : "admin-api: нет связи";

  const modules = overview.data?.modules ?? [];

  return (
    <Group gap="xs" wrap="nowrap">
      <Tooltip label={apiLabel}>
        <Badge variant="light" color={apiUp ? "green" : health.isPending ? "gray" : "red"} data-testid="api-connection">
          {apiUp ? "API" : health.isPending ? "API…" : "API нет"}
        </Badge>
      </Tooltip>
      {modules.map((m) => (
        <Tooltip key={m.id ?? m.name} label={`${m.name ?? m.id}: ${m.health ?? "unknown"}`}>
          <Group gap={4} wrap="nowrap">
            <Text size="xs" c="dimmed" visibleFrom="md">
              {shortStage(m.stage_id, m.id)}
            </Text>
            <ModuleHealthBadge health={m.health} />
          </Group>
        </Tooltip>
      ))}
    </Group>
  );
}

function shortStage(stage?: string, id?: string): string {
  if (stage) {
    return stage;
  }
  return id ?? "модуль";
}
