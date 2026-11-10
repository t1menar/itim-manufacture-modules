import { Anchor, Button, Group, Paper, Stack, Table, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api/client";
import { ProblemError } from "../api/problem";
import { showProblem } from "../lib/toasts";
import { ConfirmAction } from "../components/ConfirmAction";
import { LoadingLabel, QueryError } from "../components/QueryState";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../lib/format";
import { shortId } from "./ProductionsPage";

type Action =
  | { kind: "cancel"; jobId: string }
  | { kind: "retry"; variantId: string }
  | { kind: "skip"; variantId: string };

export function ProductionDetailPage() {
  const { id } = useParams({ from: "/productions/$id" });
  const qc = useQueryClient();
  const [action, setAction] = useState<Action | null>(null);

  const q = useQuery({
    queryKey: ["production", id],
    queryFn: async ({ signal }) => {
      const { data } = await api.GET("/api/v1/productions/{id}", { signal, params: { path: { id } } });
      if (!data) {
        throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
      }
      return data;
    },
    refetchInterval: 10_000,
  });

  const mut = useMutation({
    mutationFn: async ({ act, reason }: { act: Action; reason: string }) => {
      if (act.kind === "cancel") {
        const res = await api.POST("/api/v1/jobs/{id}/cancel", {
          params: { path: { id: act.jobId } },
          body: { reason },
        });
        return res.data;
      }
      if (act.kind === "retry") {
        const res = await api.POST("/api/v1/variants/{id}/retry", { params: { path: { id: act.variantId } } });
        return res.data;
      }
      const res = await api.POST("/api/v1/variants/{id}/skip", {
        params: { path: { id: act.variantId } },
        body: { reason },
      });
      return res.data;
    },
    onSuccess: () => {
      setAction(null);
      void qc.invalidateQueries({ queryKey: ["production", id] });
      void qc.invalidateQueries({ queryKey: ["productions"] });
    },
    onError: (err) => {
      showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" });
    },
  });

  if (q.isPending) {
    return <LoadingLabel label="Загружаем производство…" />;
  }
  if (q.isError) {
    return <QueryError title="Production" error={q.error} />;
  }

  const p = q.data;
  const jobs = p.jobs ?? [];
  const variants = p.variants ?? [];
  const events = p.events ?? [];

  return (
    <Stack gap="md">
      <div>
        <Anchor component={Link} to="/productions" size="sm">
          ← Все productions
        </Anchor>
        <Title order={2} mt={4}>
          Production {shortId(p.id)}
        </Title>
        <Group gap="sm" mt={4}>
          <StatusBadge status={p.status} />
          <Text size="sm" c="dimmed">
            идея {p.idea_ref} · прогон {p.run_no} · ревизия {p.rev} · {p.language}
          </Text>
        </Group>
        <Text size="sm" c="dimmed">
          начато {formatDateTime(p.started_at)}
          {p.finished_at ? ` · завершено ${formatDateTime(p.finished_at)}` : ""}
        </Text>
      </div>

      <Paper withBorder p="md" radius="md">
        <Title order={3} mb="sm">
          Варианты
        </Title>
        {variants.length === 0 ? (
          <Text c="dimmed">Нет вариантов.</Text>
        ) : (
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ID</Table.Th>
                <Table.Th>Язык</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Ревизия</Table.Th>
                <Table.Th>Каналы</Table.Th>
                <Table.Th>Действия</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {variants.map((v) => (
                <Table.Tr key={v.id}>
                  <Table.Td>
                    <Text ff="monospace" size="sm">
                      {shortId(v.id)}
                    </Text>
                  </Table.Td>
                  <Table.Td>{v.language}</Table.Td>
                  <Table.Td>
                    <StatusBadge status={v.status} />
                  </Table.Td>
                  <Table.Td>{v.rev ?? "—"}</Table.Td>
                  <Table.Td>{Array.isArray(v.channels) ? v.channels.join(", ") : "—"}</Table.Td>
                  <Table.Td>
                    <Group gap="xs">
                      <Button
                        size="xs"
                        variant="light"
                        disabled={v.status !== "needs_attention"}
                        onClick={() => setAction({ kind: "retry", variantId: String(v.id) })}
                      >
                        Повторить
                      </Button>
                      <Button
                        size="xs"
                        variant="light"
                        color="orange"
                        disabled={v.status !== "needs_attention"}
                        onClick={() => setAction({ kind: "skip", variantId: String(v.id) })}
                      >
                        Пропустить
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Title order={3} mb="sm">
          Джобы
        </Title>
        {jobs.length === 0 ? (
          <Text c="dimmed">Нет джоб.</Text>
        ) : (
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ID</Table.Th>
                <Table.Th>Стадия</Table.Th>
                <Table.Th>Модуль</Table.Th>
                <Table.Th>Попытка</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Ревизия</Table.Th>
                <Table.Th>Обновлено</Table.Th>
                <Table.Th></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {jobs.map((j) => {
                const live = ["queued", "dispatching", "dispatched", "running"].includes(j.status ?? "");
                return (
                  <Table.Tr key={j.id}>
                    <Table.Td>
                      <Text ff="monospace" size="sm">
                        {shortId(j.id)}
                      </Text>
                    </Table.Td>
                    <Table.Td>{j.stage_id}</Table.Td>
                    <Table.Td>{j.module_id ?? "—"}</Table.Td>
                    <Table.Td>{j.attempt}</Table.Td>
                    <Table.Td>
                      <StatusBadge status={j.status} />
                      {j.cancel_requested ? (
                        <Text size="xs" c="orange">
                          отмена запрошена
                        </Text>
                      ) : null}
                    </Table.Td>
                    <Table.Td>{j.rev ?? "—"}</Table.Td>
                    <Table.Td>{formatDateTime(j.updated_at ?? j.created_at)}</Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        color="red"
                        variant="light"
                        disabled={!live}
                        onClick={() => setAction({ kind: "cancel", jobId: String(j.id) })}
                      >
                        Отменить
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        )}
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Title order={3} mb="sm">
          Таймлайн
        </Title>
        {events.length === 0 ? (
          <Text c="dimmed">Событий нет.</Text>
        ) : (
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Время</Table.Th>
                <Table.Th>Тип</Table.Th>
                <Table.Th>Актор</Table.Th>
                <Table.Th>Джоб / вариант</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {events.map((e) => (
                <Table.Tr key={e.id}>
                  <Table.Td>{formatDateTime(e.at)}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{e.type}</Text>
                  </Table.Td>
                  <Table.Td>{e.actor}</Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed" ff="monospace">
                      {e.job_id ? `job ${shortId(String(e.job_id))}` : ""}
                      {e.variant_id ? ` variant ${shortId(String(e.variant_id))}` : ""}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>

      <ConfirmAction
        opened={action?.kind === "cancel"}
        onClose={() => setAction(null)}
        title="Отменить джоб"
        message="Джоб будет остановлен, если он ещё живой."
        confirmLabel="Отменить джоб"
        withReason
        reasonLabel="Причина (необязательно)"
        loading={mut.isPending}
        onConfirm={(reason) => action && mut.mutate({ act: action, reason })}
      />
      <ConfirmAction
        opened={action?.kind === "retry"}
        onClose={() => setAction(null)}
        title="Повторить вариант"
        message="Будет создан новый джоб для варианта в статусе «нужно внимание»."
        confirmLabel="Повторить"
        loading={mut.isPending}
        onConfirm={(reason) => action && mut.mutate({ act: action, reason })}
      />
      <ConfirmAction
        opened={action?.kind === "skip"}
        onClose={() => setAction(null)}
        title="Пропустить вариант"
        message="Вариант будет пропущен. Укажите причину — она обязательна."
        confirmLabel="Пропустить вариант"
        reasonRequired
        loading={mut.isPending}
        onConfirm={(reason) => action && mut.mutate({ act: action, reason })}
      />
    </Stack>
  );
}
