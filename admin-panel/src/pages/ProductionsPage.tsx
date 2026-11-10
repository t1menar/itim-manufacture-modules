import { Button, Group, Paper, Select, Stack, Table, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api/client";
import { ProblemError } from "../api/problem";
import { LoadingLabel, QueryError } from "../components/QueryState";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../lib/format";
import { useState } from "react";

const STATUSES = [
  { value: "", label: "Все статусы" },
  { value: "running", label: "Идёт" },
  { value: "done", label: "Готово" },
  { value: "failed", label: "Ошибка" },
  { value: "cancelled", label: "Отменено" },
];

export function ProductionsPage() {
  const [status, setStatus] = useState<string>("");
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<(string | undefined)[]>([]);

  const q = useQuery({
    queryKey: ["productions", status, cursor],
    queryFn: async ({ signal }) => {
      const { data } = await api.GET("/api/v1/productions", {
        signal,
        params: { query: { status: status || undefined, limit: 20, cursor } },
      });
      if (!data) {
        throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
      }
      return data;
    },
  });

  if (q.isPending) {
    return <LoadingLabel label="Загружаем productions…" />;
  }
  if (q.isError) {
    return <QueryError title="Productions" error={q.error} />;
  }

  const items = q.data.items ?? [];
  const next = q.data.next_cursor ?? undefined;

  return (
    <Stack gap="md">
      <div>
        <Title order={2}>Productions</Title>
        <Text c="dimmed" size="sm">
          Производства, джобы и варианты из core через admin-api
        </Text>
      </div>
      <Group>
        <Select
          label="Статус"
          data={STATUSES}
          value={status}
          onChange={(v) => {
            setStatus(v ?? "");
            setCursor(undefined);
            setHistory([]);
          }}
          w={220}
          allowDeselect={false}
        />
      </Group>
      <Paper withBorder p="md" radius="md">
        {items.length === 0 ? (
          <Text c="dimmed">Пока нет производств.</Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ID</Table.Th>
                <Table.Th>Идея</Table.Th>
                <Table.Th>Прогон</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Язык</Table.Th>
                <Table.Th>Ревизия</Table.Th>
                <Table.Th>Начато</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((p) => (
                <Table.Tr key={p.id}>
                  <Table.Td>
                    <Link to="/productions/$id" params={{ id: String(p.id) }}>
                      <Text ff="monospace" size="sm">
                        {shortId(p.id)}
                      </Text>
                    </Link>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{p.idea_ref ?? "—"}</Text>
                    <Text size="xs" c="dimmed">
                      rev {p.idea_rev ?? "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>{p.run_no ?? "—"}</Table.Td>
                  <Table.Td>
                    <StatusBadge status={p.status} />
                  </Table.Td>
                  <Table.Td>{p.language ?? "—"}</Table.Td>
                  <Table.Td>{p.rev ?? "—"}</Table.Td>
                  <Table.Td>{formatDateTime(p.started_at)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        <Group mt="md">
          <Button
            variant="default"
            disabled={history.length === 0}
            onClick={() => {
              const prev = history[history.length - 1];
              setHistory(history.slice(0, -1));
              setCursor(prev);
            }}
          >
            Назад
          </Button>
          <Button
            variant="default"
            disabled={!next}
            onClick={() => {
              setHistory([...history, cursor]);
              setCursor(String(next));
            }}
          >
            Дальше
          </Button>
        </Group>
      </Paper>
    </Stack>
  );
}

export function shortId(id: string | undefined): string {
  if (!id) {
    return "—";
  }
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}
