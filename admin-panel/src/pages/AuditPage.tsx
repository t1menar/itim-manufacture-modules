import { Button, Group, Paper, Select, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { ProblemError } from "../api/problem";
import { LoadingLabel, QueryError } from "../components/QueryState";
import { formatDateTime } from "../lib/format";

type AuditRow = {
  id?: number;
  at?: string;
  actor?: string;
  action?: string;
  resource_type?: string | null;
  resource_id?: string | null;
  outcome?: string;
  http_status?: number;
  problem_code?: string | null;
  request_id?: string | null;
  details?: Record<string, unknown> | null;
};

type Filters = {
  actor: string;
  action: string;
  outcome: string;
  from: string;
  to: string;
};

const EMPTY: Filters = { actor: "", action: "", outcome: "", from: "", to: "" };

const OUTCOMES = [
  { value: "", label: "Все исходы" },
  { value: "ok", label: "ok" },
  { value: "denied", label: "denied" },
  { value: "error", label: "error" },
];

function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

function resourceOf(row: AuditRow): string {
  const type = row.resource_type?.trim() ?? "";
  const id = row.resource_id?.trim() ?? "";
  if (type && id) return `${type}:${id}`;
  return type || id || "—";
}

function detailsOf(row: AuditRow): string {
  const d = row.details;
  if (!d || (typeof d === "object" && Object.keys(d).length === 0)) return "—";
  try {
    return JSON.stringify(d);
  } catch {
    return "—";
  }
}

export function AuditPage() {
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<(string | undefined)[]>([]);

  const q = useQuery({
    queryKey: ["audit", applied, cursor],
    queryFn: async ({ signal }) => {
      const { data } = await api.GET("/api/v1/audit", {
        signal,
        params: {
          query: {
            actor: applied.actor || undefined,
            action: applied.action || undefined,
            outcome: applied.outcome ? (applied.outcome as "ok" | "denied" | "error") : undefined,
            from: toIso(applied.from),
            to: toIso(applied.to),
            cursor,
            limit: 20,
          },
        },
      });
      if (!data) {
        throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
      }
      return data;
    },
  });

  if (q.isPending) {
    return <LoadingLabel label="Загружаем журнал…" />;
  }
  if (q.isError) {
    return <QueryError title="Журнал" error={q.error} />;
  }

  const items = (q.data.items ?? []) as AuditRow[];
  const next = q.data.next_cursor ?? undefined;

  const apply = (nextFilters: Filters) => {
    setApplied(nextFilters);
    setCursor(undefined);
    setHistory([]);
  };

  return (
    <Stack gap="md">
      <div>
        <Title order={2}>Журнал</Title>
        <Text c="dimmed" size="sm">
          Действия админа из audit_log. Фильтры: актор, действие, исход, интервал. Значения секретов в журнал не пишутся.
        </Text>
      </div>
      <Paper withBorder p="md">
        <Group align="flex-end" wrap="wrap">
          <TextInput
            label="Актор"
            value={draft.actor}
            onChange={(e) => setDraft((f) => ({ ...f, actor: e.currentTarget.value }))}
            autoComplete="off"
            style={{ minWidth: 160 }}
          />
          <TextInput
            label="Действие"
            value={draft.action}
            onChange={(e) => setDraft((f) => ({ ...f, action: e.currentTarget.value }))}
            autoComplete="off"
            style={{ minWidth: 200 }}
          />
          <Select
            label="Исход"
            data={OUTCOMES}
            value={draft.outcome}
            onChange={(v) => setDraft((f) => ({ ...f, outcome: v ?? "" }))}
            allowDeselect={false}
            w={160}
          />
          <TextInput
            label="С (локальное время)"
            type="datetime-local"
            value={draft.from}
            onChange={(e) => setDraft((f) => ({ ...f, from: e.currentTarget.value }))}
          />
          <TextInput
            label="По"
            type="datetime-local"
            value={draft.to}
            onChange={(e) => setDraft((f) => ({ ...f, to: e.currentTarget.value }))}
          />
          <Button onClick={() => apply(draft)}>Применить</Button>
          <Button
            variant="default"
            onClick={() => {
              setDraft(EMPTY);
              apply(EMPTY);
            }}
          >
            Сбросить
          </Button>
        </Group>
      </Paper>
      <Paper withBorder>
        {items.length === 0 ? (
          <Text c="dimmed" p="md">
            Записей нет.
          </Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Когда</Table.Th>
                <Table.Th>Актор</Table.Th>
                <Table.Th>Действие</Table.Th>
                <Table.Th>Ресурс</Table.Th>
                <Table.Th>Исход</Table.Th>
                <Table.Th>HTTP</Table.Th>
                <Table.Th>Код</Table.Th>
                <Table.Th>Детали</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((row, i) => (
                <Table.Tr key={String(row.id ?? `${row.at}-${i}`)}>
                  <Table.Td>{formatDateTime(row.at)}</Table.Td>
                  <Table.Td>{row.actor ?? "—"}</Table.Td>
                  <Table.Td>{row.action ?? "—"}</Table.Td>
                  <Table.Td>{resourceOf(row)}</Table.Td>
                  <Table.Td>{row.outcome ?? "—"}</Table.Td>
                  <Table.Td>{row.http_status ?? "—"}</Table.Td>
                  <Table.Td>{row.problem_code || "—"}</Table.Td>
                  <Table.Td>
                    <Text size="xs" ff="monospace">
                      {detailsOf(row)}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        <Group p="md">
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
