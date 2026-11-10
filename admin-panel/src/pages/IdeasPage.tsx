import { Alert, Button, Group, Paper, Select, Stack, Table, Text, TextInput, Textarea, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { ProblemError } from "../api/problem";
import { ConfirmAction } from "../components/ConfirmAction";
import { LoadingLabel, QueryError } from "../components/QueryState";
import { StatusBadge } from "../components/StatusBadge";
import { formatStatus } from "../lib/format";
import { showProblem } from "../lib/toasts";

export const NOT_SUPPORTED_MESSAGE = "module-video does not support this yet";

type Topic = {
  id?: string | number;
  code?: string;
  title?: string;
  description?: string | null;
  default_tags?: string[] | null;
  default_platforms?: string[] | null;
  active?: boolean;
};

type Idea = {
  id?: string | number;
  topic_id?: string | number;
  title?: string;
  description?: string | null;
  hook?: string | null;
  language?: string | null;
  priority?: number | null;
  tags?: string[] | null;
  author?: string | null;
  status?: string;
  rev?: number;
};

const IDEA_STATUSES = [
  { value: "", label: "Все статусы" },
  { value: "draft", label: formatStatus("draft") },
  { value: "ready", label: formatStatus("ready") },
  { value: "queued", label: formatStatus("queued") },
  { value: "dispatched", label: formatStatus("dispatched") },
  { value: "in_production", label: formatStatus("in_production") },
  { value: "done", label: formatStatus("done") },
  { value: "failed", label: formatStatus("failed") },
  { value: "cancelled", label: formatStatus("cancelled") },
  { value: "archived", label: formatStatus("archived") },
];

export function isNotImplemented(error: unknown): boolean {
  return error instanceof ProblemError && error.status === 404;
}

function idOf(v: string | number | undefined | null): string {
  return v == null ? "" : String(v);
}

export function IdeasPage() {
  const topicsQ = useQuery({
    queryKey: ["video", "topics"],
    queryFn: async ({ signal }) => {
      const { data } = await api.GET("/api/v1/topics", { signal });
      if (data === undefined) throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
      return (data.items ?? []) as Topic[];
    },
    retry: false,
    meta: { silent: true },
  });
  const [status, setStatus] = useState("");
  const [topicId, setTopicId] = useState("");
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<(string | undefined)[]>([]);

  const ideasQ = useQuery({
    queryKey: ["video", "ideas", status, topicId, cursor],
    queryFn: async ({ signal }) => {
      const { data } = await api.GET("/api/v1/ideas", {
        signal,
        params: { query: { status: status || undefined, topic_id: topicId || undefined, limit: 20, cursor } },
      });
      if (data === undefined) throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
      return data as { items?: Idea[]; next_cursor?: string };
    },
    retry: false,
    meta: { silent: true },
  });

  const unsupported = isNotImplemented(topicsQ.error) && isNotImplemented(ideasQ.error);
  const pending = (topicsQ.isPending || ideasQ.isPending) && !topicsQ.isError && !ideasQ.isError;

  if (pending) {
    return <LoadingLabel label="Загружаем идеи и темы…" />;
  }
  if (unsupported) {
    return (
      <Stack gap="md">
        <Title order={2}>Идеи и темы</Title>
        <Alert color="yellow" title="Пока недоступно">
          {NOT_SUPPORTED_MESSAGE}. module-video пока не отдаёт /admin/v1/ideas и /admin/v1/topics. Контракт:
          admin-api/docs/VIDEO_ADMIN_ROUTES.md. Когда модуль добавит эти роуты, экран заработает без изменений в
          admin-api.
        </Alert>
      </Stack>
    );
  }
  if (topicsQ.isError && ideasQ.isError) {
    return <QueryError title="Идеи и темы" error={topicsQ.error ?? ideasQ.error} />;
  }

  const topics = topicsQ.data ?? [];
  const ideas = ideasQ.data?.items ?? [];
  const next = ideasQ.data?.next_cursor;

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Идеи и темы</Title>
        <Text c="dimmed" size="sm">
          CRUD по контракту VIDEO_ADMIN_ROUTES.md. Идеи живут в БД module-video.
        </Text>
      </div>
      {topicsQ.isError ? (
        isNotImplemented(topicsQ.error) ? (
          <Alert color="yellow" title="Темы недоступны">
            {NOT_SUPPORTED_MESSAGE}
          </Alert>
        ) : (
          <QueryError title="Темы" error={topicsQ.error} />
        )
      ) : (
        <TopicsBlock topics={topics} />
      )}
      {ideasQ.isError ? (
        isNotImplemented(ideasQ.error) ? (
          <Alert color="yellow" title="Идеи недоступны">
            {NOT_SUPPORTED_MESSAGE}
          </Alert>
        ) : (
          <QueryError title="Идеи" error={ideasQ.error} />
        )
      ) : (
        <Stack gap="sm">
          <Group justify="space-between" align="flex-end">
            <Title order={4}>Идеи</Title>
            <IdeaForm topics={topics} />
          </Group>
          <Group>
            <Select
              label="Статус"
              data={IDEA_STATUSES}
              value={status}
              onChange={(v) => {
                setStatus(v ?? "");
                setCursor(undefined);
                setHistory([]);
              }}
              allowDeselect={false}
              w={220}
            />
            <Select
              label="Тема"
              data={[{ value: "", label: "Все темы" }, ...topics.map((t) => ({ value: idOf(t.id), label: t.title || t.code || idOf(t.id) }))]}
              value={topicId}
              onChange={(v) => {
                setTopicId(v ?? "");
                setCursor(undefined);
                setHistory([]);
              }}
              allowDeselect={false}
              w={220}
            />
          </Group>
          <IdeasTable topics={topics} ideas={ideas} />
          <Group>
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
        </Stack>
      )}
    </Stack>
  );
}

function TopicsBlock({ topics }: { topics: Topic[] }) {
  const [delId, setDelId] = useState<string | null>(null);
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: async (id: string) => {
      await api.DELETE("/api/v1/topics/{id}", { params: { path: { id } } });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Тема удалена", message: delId ?? "" });
      setDelId(null);
      await qc.invalidateQueries({ queryKey: ["video", "topics"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={4}>Темы</Title>
        <TopicForm />
      </Group>
      <Paper withBorder>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Код</Table.Th>
              <Table.Th>Название</Table.Th>
              <Table.Th>Описание</Table.Th>
              <Table.Th>Активна</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {topics.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed">Тем нет.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              topics.map((t) => (
                <Table.Tr key={idOf(t.id)}>
                  <Table.Td>{t.code ?? "—"}</Table.Td>
                  <Table.Td>{t.title ?? "—"}</Table.Td>
                  <Table.Td>{t.description || "—"}</Table.Td>
                  <Table.Td>{t.active === false ? "нет" : "да"}</Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <TopicForm initial={t} />
                      <Button size="xs" color="red" variant="light" onClick={() => setDelId(idOf(t.id))}>
                        Удалить
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      <ConfirmAction
        opened={delId !== null}
        onClose={() => setDelId(null)}
        title="Удалить тему"
        message={`Удалить тему ${delId}? Если на ней есть живые идеи, модуль вернёт 409.`}
        confirmLabel="Удалить тему"
        loading={del.isPending}
        onConfirm={() => delId && del.mutate(delId)}
      />
    </Stack>
  );
}

function TopicForm({ initial }: { initial?: Topic }) {
  const qc = useQueryClient();
  const [opened, setOpened] = useState(false);
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [active, setActive] = useState("true");
  const create = !initial;

  const mut = useMutation({
    mutationFn: async () => {
      const body = { code: code.trim(), title: title.trim(), description: description.trim() || undefined, active: active === "true" };
      if (create) {
        await api.POST("/api/v1/topics", { body });
        return;
      }
      await api.PATCH("/api/v1/topics/{id}", { params: { path: { id: idOf(initial.id) } }, body });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: create ? "Тема создана" : "Тема обновлена", message: title || code });
      setOpened(false);
      await qc.invalidateQueries({ queryKey: ["video", "topics"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  return (
    <>
      <Button
        size="xs"
        variant={create ? "filled" : "light"}
        onClick={() => {
          setCode(initial?.code ?? "");
          setTitle(initial?.title ?? "");
          setDescription(initial?.description ?? "");
          setActive(initial?.active === false ? "false" : "true");
          setOpened(true);
        }}
      >
        {create ? "Добавить тему" : "Изменить"}
      </Button>
      <ConfirmAction
        opened={opened}
        onClose={() => setOpened(false)}
        title={create ? "Новая тема" : "Изменить тему"}
        message="Поля соответствуют VIDEO_ADMIN_ROUTES.md."
        confirmLabel="Сохранить"
        reasonRequired={false}
        loading={mut.isPending}
        extra={
          <Stack>
            <TextInput label="Код" value={code} onChange={(e) => setCode(e.currentTarget.value)} required autoComplete="off" />
            <TextInput label="Название темы" value={title} onChange={(e) => setTitle(e.currentTarget.value)} required autoComplete="off" />
            <Textarea label="Описание" value={description} onChange={(e) => setDescription(e.currentTarget.value)} autosize />
            <Select label="Активна" data={[{ value: "true", label: "да" }, { value: "false", label: "нет" }]} value={active} onChange={(v) => setActive(v ?? "true")} allowDeselect={false} />
          </Stack>
        }
        onConfirm={() => {
          if (!code.trim() || !title.trim()) {
            notifications.show({ color: "yellow", title: "Нужны код и название", message: "Заполните обязательные поля." });
            return;
          }
          mut.mutate();
        }}
      />
    </>
  );
}

function IdeasTable({ topics, ideas }: { topics: Topic[]; ideas: Idea[] }) {
  const byId = new Map(topics.map((t) => [idOf(t.id), t]));
  const [delId, setDelId] = useState<string | null>(null);
  const qc = useQueryClient();
  const invalidate = async () => qc.invalidateQueries({ queryKey: ["video", "ideas"] });

  const action = useMutation({
    mutationFn: async (input: { id: string; kind: "ready" | "queue" | "delete" }) => {
      if (input.kind === "ready") {
        await api.POST("/api/v1/ideas/{id}/ready", { params: { path: { id: input.id } } });
        return "ready";
      }
      if (input.kind === "queue") {
        await api.POST("/api/v1/ideas/{id}/queue", { params: { path: { id: input.id } } });
        return "queue";
      }
      await api.DELETE("/api/v1/ideas/{id}", { params: { path: { id: input.id } } });
      return "delete";
    },
    onSuccess: async (kind) => {
      notifications.show({
        color: "green",
        title: kind === "delete" ? "Идея удалена" : kind === "ready" ? "Идея готова" : "Идея в очереди",
        message: "",
      });
      setDelId(null);
      await invalidate();
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  return (
    <>
      <Paper withBorder>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Название</Table.Th>
              <Table.Th>Тема</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>Язык</Table.Th>
              <Table.Th>Автор</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {ideas.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed">Идей нет.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              ideas.map((idea) => {
                const topic = byId.get(idOf(idea.topic_id));
                const id = idOf(idea.id);
                const st = (idea.status ?? "").toLowerCase();
                return (
                  <Table.Tr key={id}>
                    <Table.Td>{idea.title ?? id}</Table.Td>
                    <Table.Td>{topic?.title || topic?.code || idOf(idea.topic_id) || "—"}</Table.Td>
                    <Table.Td>
                      <StatusBadge status={idea.status} />
                    </Table.Td>
                    <Table.Td>{idea.language || "—"}</Table.Td>
                    <Table.Td>{idea.author || "—"}</Table.Td>
                    <Table.Td>
                      <Group gap="xs" justify="flex-end">
                        <IdeaForm topics={topics} initial={idea} />
                        {st === "draft" ? (
                          <Button size="xs" variant="light" onClick={() => action.mutate({ id, kind: "ready" })} loading={action.isPending}>
                            В ready
                          </Button>
                        ) : null}
                        {st === "ready" ? (
                          <Button size="xs" variant="light" onClick={() => action.mutate({ id, kind: "queue" })} loading={action.isPending}>
                            В очередь
                          </Button>
                        ) : null}
                        <Button size="xs" color="red" variant="light" onClick={() => setDelId(id)}>
                          Удалить
                        </Button>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                );
              })
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      <ConfirmAction
        opened={delId !== null}
        onClose={() => setDelId(null)}
        title="Удалить идею"
        message="Удаление возможно только если нет живого production, иначе модуль вернёт 409."
        confirmLabel="Удалить идею"
        loading={action.isPending}
        onConfirm={() => delId && action.mutate({ id: delId, kind: "delete" })}
      />
    </>
  );
}

function IdeaForm({ topics, initial }: { topics: Topic[]; initial?: Idea }) {
  const qc = useQueryClient();
  const [opened, setOpened] = useState(false);
  const [topicId, setTopicId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hook, setHook] = useState("");
  const [language, setLanguage] = useState("ru");
  const [author, setAuthor] = useState("");
  const create = !initial;

  const mut = useMutation({
    mutationFn: async () => {
      const body = {
        topic_id: topicId,
        title: title.trim(),
        description: description.trim() || undefined,
        hook: hook.trim() || undefined,
        language: language.trim() || undefined,
        author: author.trim() || undefined,
      };
      if (create) {
        await api.POST("/api/v1/ideas", { body });
        return;
      }
      await api.PATCH("/api/v1/ideas/{id}", { params: { path: { id: idOf(initial.id) } }, body });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: create ? "Идея создана" : "Идея обновлена", message: title });
      setOpened(false);
      await qc.invalidateQueries({ queryKey: ["video", "ideas"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  return (
    <>
      <Button
        size="xs"
        variant={create ? "filled" : "light"}
        onClick={() => {
          setTopicId(idOf(initial?.topic_id) || idOf(topics[0]?.id));
          setTitle(initial?.title ?? "");
          setDescription(initial?.description ?? "");
          setHook(initial?.hook ?? "");
          setLanguage(initial?.language ?? "ru");
          setAuthor(initial?.author ?? "");
          setOpened(true);
        }}
      >
        {create ? "Добавить идею" : "Изменить"}
      </Button>
      <ConfirmAction
        opened={opened}
        onClose={() => setOpened(false)}
        title={create ? "Новая идея" : "Изменить идею"}
        message="Новая идея создаётся в статусе draft."
        confirmLabel="Сохранить"
        reasonRequired={false}
        loading={mut.isPending}
        extra={
          <Stack>
            <Select
              label="Тема"
              data={topics.map((t) => ({ value: idOf(t.id), label: t.title || t.code || idOf(t.id) }))}
              value={topicId}
              onChange={(v) => setTopicId(v ?? "")}
              allowDeselect={false}
              required
            />
            <TextInput label="Название идеи" value={title} onChange={(e) => setTitle(e.currentTarget.value)} required autoComplete="off" />
            <Textarea label="Описание" value={description} onChange={(e) => setDescription(e.currentTarget.value)} autosize />
            <TextInput label="Hook" value={hook} onChange={(e) => setHook(e.currentTarget.value)} autoComplete="off" />
            <TextInput label="Язык" value={language} onChange={(e) => setLanguage(e.currentTarget.value)} autoComplete="off" />
            <TextInput label="Автор" value={author} onChange={(e) => setAuthor(e.currentTarget.value)} autoComplete="off" />
          </Stack>
        }
        onConfirm={() => {
          if (!topicId || !title.trim()) {
            notifications.show({ color: "yellow", title: "Нужны тема и название", message: "Заполните обязательные поля." });
            return;
          }
          mut.mutate();
        }}
      />
    </>
  );
}
