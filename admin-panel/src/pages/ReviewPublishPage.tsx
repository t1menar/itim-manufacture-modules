import { Anchor, Badge, Button, Checkbox, Group, Paper, Stack, Table, Tabs, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { ProblemError } from "../api/problem";
import { showProblem } from "../lib/toasts";
import { ConfirmAction } from "../components/ConfirmAction";
import { LoadingLabel, QueryError } from "../components/QueryState";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../lib/format";

type PendingPayload = {
  pending_rejects?: PendingReject[];
  active_cards?: ActiveCard[];
};
type PendingReject = { run_id?: string; chat_id?: number | string; admin_user_id?: number | string; created_at?: string | null };
type ActiveCard = { id?: string; run_id?: string; variant_id?: string; version?: number; chat_id?: number | string; created_at?: string | null };
type ReviewRun = {
  id?: string;
  job_id?: string;
  production_id?: string;
  variant_id?: string | null;
  status?: string;
  round?: number;
  mode?: string;
  created_at?: string | null;
  finished_at?: string | null;
  error?: unknown;
};
type Intent = {
  id?: string;
  variant_id?: string;
  generation?: number;
  status?: string;
  external_post_id?: string | null;
  url?: string | null;
  published_at?: string | null;
  last_error?: unknown;
  created_at?: string | null;
  account?: { channel_id?: string; platform?: string; handle?: string; has_token?: boolean } | null;
};

const BLOCKED_REPUBLISH = new Set(["pending", "in_progress"]);

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

async function getJson<T>(path: "/api/v1/review/pending" | "/api/v1/review/runs" | "/api/v1/publish/intents" | "/api/v1/overview", signal: AbortSignal): Promise<T> {
  const { data } = await api.GET(path, { signal });
  if (!data) {
    throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
  }
  return data as T;
}

function publishModeFromOverview(data: unknown): { label: string; mode: "real" | "fake" | "unknown" } {
  const modules = asRecord(data).modules;
  const items = Array.isArray(modules) ? modules : Array.isArray(asRecord(modules).items) ? (asRecord(modules).items as unknown[]) : [];
  const pub = items.find((m) => {
    const rec = asRecord(m);
    const id = String(rec.id ?? "");
    const name = String(rec.name ?? "");
    return id === "publish-instagram" || /instagram/i.test(name) || id.startsWith("publish");
  });
  const name = String(asRecord(pub).name ?? "publish");
  if (/\breal\b/i.test(name)) {
    return { label: name, mode: "real" };
  }
  if (/\bfake\b/i.test(name)) {
    return { label: name, mode: "fake" };
  }
  return { label: name, mode: "unknown" };
}

export function ReviewPublishPage() {
  const pendingQ = useQuery({
    queryKey: ["review", "pending"],
    queryFn: ({ signal }) => getJson<PendingPayload>("/api/v1/review/pending", signal),
  });
  const runsQ = useQuery({
    queryKey: ["review", "runs"],
    queryFn: ({ signal }) => getJson<{ items?: ReviewRun[] }>("/api/v1/review/runs", signal),
  });
  const intentsQ = useQuery({
    queryKey: ["publish", "intents"],
    queryFn: ({ signal }) => getJson<{ items?: Intent[] }>("/api/v1/publish/intents", signal),
  });
  const overviewQ = useQuery({
    queryKey: ["overview"],
    queryFn: ({ signal }) => getJson<unknown>("/api/v1/overview", signal),
  });

  const firstError = pendingQ.error ?? runsQ.error ?? intentsQ.error;
  if (pendingQ.isPending && runsQ.isPending && intentsQ.isPending) {
    return <LoadingLabel label="Загружаем ревью и публикации…" />;
  }
  if (firstError && !pendingQ.data && !runsQ.data && !intentsQ.data) {
    return <QueryError title="Ревью и публикации" error={firstError} />;
  }

  const rejects = pendingQ.data?.pending_rejects ?? [];
  const cards = pendingQ.data?.active_cards ?? [];
  const runs = runsQ.data?.items ?? [];
  const intents = intentsQ.data?.items ?? [];
  const ig = overviewQ.data ? publishModeFromOverview(overviewQ.data) : null;

  return (
    <Stack gap="md">
      <div>
        <Title order={2}>Ревью и публикации</Title>
        <Text c="dimmed" size="sm">
          Очередь ревью, история прогонов и интенты публикации
        </Text>
      </div>
      {ig && (
        <Paper withBorder p="sm">
          <Group gap="sm">
            <Text size="sm" fw={500}>
              Instagram publish:
            </Text>
            <Badge color={ig.mode === "real" ? "red" : ig.mode === "fake" ? "gray" : "yellow"} variant="light">
              {ig.mode === "unknown" ? "режим не указан" : ig.mode}
            </Badge>
            <Text size="sm" c="dimmed">
              {ig.label}
            </Text>
          </Group>
        </Paper>
      )}
      <Tabs defaultValue="pending">
        <Tabs.List>
          <Tabs.Tab value="pending">Очередь ревью ({rejects.length + cards.length})</Tabs.Tab>
          <Tabs.Tab value="runs">Прогоны ({runs.length})</Tabs.Tab>
          <Tabs.Tab value="intents">Интенты ({intents.length})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="pending" pt="md">
          {pendingQ.isError ? (
            <QueryError title="Очередь ревью" error={pendingQ.error} />
          ) : (
            <PendingTables rejects={rejects} cards={cards} />
          )}
        </Tabs.Panel>
        <Tabs.Panel value="runs" pt="md">
          {runsQ.isError ? <QueryError title="Прогоны" error={runsQ.error} /> : <RunsTable runs={runs} />}
        </Tabs.Panel>
        <Tabs.Panel value="intents" pt="md">
          {intentsQ.isError ? <QueryError title="Интенты" error={intentsQ.error} /> : <IntentsTable intents={intents} />}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function PendingTables({ rejects, cards }: { rejects: PendingReject[]; cards: ActiveCard[] }) {
  return (
    <Stack>
      <Title order={4}>Ожидают причину отклонения</Title>
      <Paper withBorder>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Run</Table.Th>
              <Table.Th>Чат</Table.Th>
              <Table.Th>Админ</Table.Th>
              <Table.Th>Создано</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rejects.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={4}>
                  <Text c="dimmed">Нет ожидающих отклонений.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              rejects.map((r) => (
                <Table.Tr key={String(r.run_id)}>
                  <Table.Td>{shortId(r.run_id)}</Table.Td>
                  <Table.Td>{r.chat_id ?? "—"}</Table.Td>
                  <Table.Td>{r.admin_user_id ?? "—"}</Table.Td>
                  <Table.Td>{formatDateTime(r.created_at)}</Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      <Title order={4}>Активные карточки</Title>
      <Paper withBorder>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Карточка</Table.Th>
              <Table.Th>Run</Table.Th>
              <Table.Th>Вариант</Table.Th>
              <Table.Th>Версия</Table.Th>
              <Table.Th>Чат</Table.Th>
              <Table.Th>Создано</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {cards.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed">Нет активных карточек.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              cards.map((c) => (
                <Table.Tr key={String(c.id)}>
                  <Table.Td>{shortId(c.id)}</Table.Td>
                  <Table.Td>{shortId(c.run_id)}</Table.Td>
                  <Table.Td>{shortId(c.variant_id)}</Table.Td>
                  <Table.Td>{c.version ?? "—"}</Table.Td>
                  <Table.Td>{c.chat_id ?? "—"}</Table.Td>
                  <Table.Td>{formatDateTime(c.created_at)}</Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </Paper>
    </Stack>
  );
}

function RunsTable({ runs }: { runs: ReviewRun[] }) {
  return (
    <Paper withBorder>
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Run</Table.Th>
            <Table.Th>Статус</Table.Th>
            <Table.Th>Раунд</Table.Th>
            <Table.Th>Режим</Table.Th>
            <Table.Th>Job</Table.Th>
            <Table.Th>Создано</Table.Th>
            <Table.Th>Завершено</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {runs.length === 0 ? (
            <Table.Tr>
              <Table.Td colSpan={7}>
                <Text c="dimmed">История прогонов пуста.</Text>
              </Table.Td>
            </Table.Tr>
          ) : (
            runs.map((r) => (
              <Table.Tr key={String(r.id)}>
                <Table.Td>{shortId(r.id)}</Table.Td>
                <Table.Td>
                  <StatusBadge status={r.status} />
                </Table.Td>
                <Table.Td>{r.round ?? "—"}</Table.Td>
                <Table.Td>{r.mode ?? "—"}</Table.Td>
                <Table.Td>{shortId(r.job_id)}</Table.Td>
                <Table.Td>{formatDateTime(r.created_at)}</Table.Td>
                <Table.Td>{formatDateTime(r.finished_at)}</Table.Td>
              </Table.Tr>
            ))
          )}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}

function IntentsTable({ intents }: { intents: Intent[] }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState<Intent | null>(null);
  const [ackUnknown, setAckUnknown] = useState(false);
  const mut = useMutation({
    mutationFn: async ({ intent, reason, ack }: { intent: Intent; reason: string; ack: boolean }) => {
      const id = String(intent.id ?? "");
      const body = {
        reason,
        base_generation: intent.generation ?? 0,
        acknowledge_unknown_risk: ack || undefined,
      };
      await api.POST("/api/v1/publish-intents/{id}/republish", {
        params: { path: { id } },
        body: body as { reason: string; base_generation?: number },
      });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Повторная публикация", message: "Запрос принят." });
      setTarget(null);
      setAckUnknown(false);
      await qc.invalidateQueries({ queryKey: ["publish", "intents"] });
    },
    onError: (err) => {
      showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" });
    },
  });

  return (
    <>
      <Paper withBorder>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Интент</Table.Th>
              <Table.Th>Аккаунт</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>Поколение</Table.Th>
              <Table.Th>Permalink</Table.Th>
              <Table.Th>Опубликовано</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {intents.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={7}>
                  <Text c="dimmed">Интентов пока нет.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              intents.map((it) => {
                const blocked = BLOCKED_REPUBLISH.has((it.status ?? "").toLowerCase());
                const handle = it.account?.handle ? `@${it.account.handle.replace(/^@/, "")}` : "—";
                return (
                  <Table.Tr key={String(it.id)}>
                    <Table.Td>{shortId(it.id)}</Table.Td>
                    <Table.Td>{handle}</Table.Td>
                    <Table.Td>
                      <StatusBadge status={it.status} />
                    </Table.Td>
                    <Table.Td>{it.generation ?? "—"}</Table.Td>
                    <Table.Td>
                      {it.url ? (
                        <Anchor href={it.url} target="_blank" rel="noreferrer" size="sm">
                          ссылка
                        </Anchor>
                      ) : (
                        "—"
                      )}
                    </Table.Td>
                    <Table.Td>{formatDateTime(it.published_at)}</Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="light"
                        disabled={blocked || !it.id}
                        onClick={() => {
                          setAckUnknown(false);
                          setTarget(it);
                        }}
                      >
                        Повторить публикацию
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                );
              })
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      <ConfirmAction
        opened={target !== null}
        onClose={() => {
          setTarget(null);
          setAckUnknown(false);
        }}
        title="Повторить публикацию"
        message={
          target?.status === "unknown"
            ? "Укажите обязательную причину. Текущий статус unknown — подтвердите, что риск осознан."
            : "Укажите обязательную причину повторной публикации. Будет отправлено текущее поколение интента."
        }
        confirmLabel="Повторить публикацию"
        reasonRequired
        loading={mut.isPending}
        extra={
          target?.status === "unknown" ? (
            <Checkbox
              label="Подтверждаю риск (acknowledge_unknown_risk)"
              checked={ackUnknown}
              onChange={(e) => setAckUnknown(e.currentTarget.checked)}
            />
          ) : null
        }
        onConfirm={(reason) => {
          if (!target) {
            return;
          }
          if (target.status === "unknown" && !ackUnknown) {
            notifications.show({
              color: "yellow",
              title: "Нужно подтверждение",
              message: "Для статуса unknown отметьте, что риск осознан.",
            });
            return;
          }
          mut.mutate({ intent: target, reason, ack: ackUnknown });
        }}
      />
    </>
  );
}

function shortId(id: string | undefined): string {
  if (!id) {
    return "—";
  }
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}
