import { Badge, Group, Loader, Paper, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { fetchOverview } from "../api/client";
import { formatProblem, ProblemError } from "../api/problem";
import { ModuleHealthBadge } from "../components/ModuleHealthBadge";

function countSummary(counts: Record<string, number> | undefined): { total: number; parts: string } {
  const entries = Object.entries(counts ?? {});
  const total = entries.reduce((s, [, n]) => s + n, 0);
  const parts = entries.length ? entries.map(([k, n]) => `${k}: ${n}`).join(" · ") : "нет записей";
  return { total, parts };
}

export function OverviewPage() {
  const q = useQuery({
    queryKey: ["overview"],
    queryFn: ({ signal }) => fetchOverview(signal),
    refetchInterval: 10_000,
  });

  if (q.isPending) {
    return (
      <Group gap="sm">
        <Loader size="sm" />
        <Text c="dimmed">Загружаем обзор…</Text>
      </Group>
    );
  }
  if (q.isError) {
    const msg = q.error instanceof ProblemError ? formatProblem(q.error.problem) : q.error.message;
    return (
      <Stack>
        <Title order={2}>Обзор</Title>
        <Text c="red">{msg}</Text>
      </Stack>
    );
  }

  const data = q.data;
  const productions = countSummary(data.productions);
  const jobs = countSummary(data.jobs);
  const variants = countSummary(data.variants);
  const modules = data.modules ?? [];

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Обзор</Title>
        <Text c="dimmed" size="sm">
          Живые данные из admin-api · обновление каждые 10 с
        </Text>
      </div>
      <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md">
        <StatCard label="Productions" value={String(productions.total)} hint={productions.parts} />
        <StatCard label="Jobs" value={String(jobs.total)} hint={jobs.parts} />
        <StatCard label="Variants" value={String(variants.total)} hint={variants.parts} />
        <StatCard label="Outbox (pending)" value={String(data.outbox_pending ?? 0)} hint="очередь core" />
      </SimpleGrid>
      <Paper withBorder p="md" radius="md">
        <Title order={3} mb="sm">
          Модули
        </Title>
        {modules.length === 0 ? (
          <Text c="dimmed">Модули не зарегистрированы.</Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Модуль</Table.Th>
                <Table.Th>Стадия</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Активен</Table.Th>
                <Table.Th>Последний heartbeat</Table.Th>
                <Table.Th>Endpoint</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {modules.map((m) => (
                <Table.Tr key={m.id ?? m.name}>
                  <Table.Td>
                    <Text fw={600}>{m.name ?? m.id}</Text>
                    <Text size="xs" c="dimmed">
                      {m.id}
                    </Text>
                  </Table.Td>
                  <Table.Td>{m.stage_id ?? "—"}</Table.Td>
                  <Table.Td>
                    <ModuleHealthBadge health={m.health} />
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light" color={m.active ? "green" : "gray"}>
                      {m.active ? "да" : "нет"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{formatTime(m.last_seen_at)}</Table.Td>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {m.endpoint ?? "—"}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>
    </Stack>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Paper withBorder p="md" radius="md">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fz={28} fw={700} lh={1.2}>
        {value}
      </Text>
      <Text size="xs" c="dimmed" mt={4}>
        {hint}
      </Text>
    </Paper>
  );
}

function formatTime(iso: string | undefined): string {
  if (!iso) {
    return "нет данных";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleString("ru-RU", { timeZone: "Europe/Stockholm" });
}
