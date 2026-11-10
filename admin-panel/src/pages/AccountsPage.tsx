import {
  Badge,
  Button,
  Checkbox,
  Group,
  Paper,
  PasswordInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { ProblemError } from "../api/problem";
import { ConfirmAction } from "../components/ConfirmAction";
import { LoadingLabel, QueryError } from "../components/QueryState";
import { formatDateTime } from "../lib/format";
import { publishModeFromOverview } from "../lib/publish-mode";
import { showProblem } from "../lib/toasts";

type Account = {
  id?: string;
  channel_id?: string;
  platform?: string;
  handle?: string | null;
  external_id?: string | null;
  enabled?: boolean;
  has_token?: boolean;
  updated_at?: string | null;
};

type SecretMeta = { key?: string; present?: boolean; updated_at?: string | null };

type VideoCred = {
  ref?: string;
  kind?: string;
  note?: string | null;
  updated_by?: string | null;
  updated_at?: string | null;
};

type AccountWriteBody = {
  channel_id?: string;
  platform?: string;
  handle?: string;
  external_id?: string;
  enabled?: boolean;
  access_token?: string;
};

const REVIEW_SECRET_KEYS = ["telegram.bot_token", "s3.access_key", "s3.secret_key"] as const;
const PUBLISH_SECRET_KEYS = ["instagram.default_access_token", "s3.access_key", "s3.secret_key"] as const;

function setLabel(present: boolean | undefined): string {
  return present ? "задан" : "не задан";
}

function mergeKnownSecrets(known: readonly string[], items: SecretMeta[]): SecretMeta[] {
  const byKey = new Map(items.filter((i) => i.key).map((i) => [i.key as string, i]));
  const rows: SecretMeta[] = known.map((key) => byKey.get(key) ?? { key, present: false, updated_at: null });
  for (const item of items) {
    if (item.key && !known.includes(item.key)) {
      rows.push(item);
    }
  }
  return rows;
}

async function getJson<T>(
  path: "/api/v1/publish/accounts" | "/api/v1/publish/secrets" | "/api/v1/review/secrets" | "/api/v1/video/credentials" | "/api/v1/overview",
  signal: AbortSignal,
): Promise<T> {
  const { data } = await api.GET(path, { signal });
  if (data === undefined) {
    throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
  }
  return data as T;
}

export function AccountsPage() {
  const accountsQ = useQuery({
    queryKey: ["publish", "accounts"],
    queryFn: ({ signal }) => getJson<{ accounts?: Account[] }>("/api/v1/publish/accounts", signal),
  });
  const pubSecretsQ = useQuery({
    queryKey: ["publish", "secrets"],
    queryFn: ({ signal }) => getJson<{ items?: SecretMeta[] }>("/api/v1/publish/secrets", signal),
  });
  const reviewSecretsQ = useQuery({
    queryKey: ["review", "secrets"],
    queryFn: ({ signal }) => getJson<{ items?: SecretMeta[] }>("/api/v1/review/secrets", signal),
  });
  const videoQ = useQuery({
    queryKey: ["video", "credentials"],
    queryFn: async ({ signal }) => {
      const data = await getJson<VideoCred[] | { items?: VideoCred[] }>("/api/v1/video/credentials", signal);
      return Array.isArray(data) ? data : (data.items ?? []);
    },
  });
  const overviewQ = useQuery({
    queryKey: ["overview"],
    queryFn: ({ signal }) => getJson<unknown>("/api/v1/overview", signal),
  });

  const firstError = accountsQ.error ?? pubSecretsQ.error ?? reviewSecretsQ.error ?? videoQ.error;
  if (accountsQ.isPending && pubSecretsQ.isPending && reviewSecretsQ.isPending && videoQ.isPending) {
    return <LoadingLabel label="Загружаем аккаунты и креды…" />;
  }
  if (firstError && !accountsQ.data && !pubSecretsQ.data && !reviewSecretsQ.data && !videoQ.data) {
    return <QueryError title="Аккаунты и креды" error={firstError} />;
  }

  const ig = overviewQ.data ? publishModeFromOverview(overviewQ.data) : null;

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Аккаунты и креды</Title>
        <Text c="dimmed" size="sm">
          Значения секретов никогда не показываются — только «задан» / «не задан» и время обновления. Поля ввода скрывают значение.
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
      {accountsQ.isError ? <QueryError title="Аккаунты publish" error={accountsQ.error} /> : <AccountsTable accounts={accountsQ.data?.accounts ?? []} />}
      {pubSecretsQ.isError ? (
        <QueryError title="Секреты publish" error={pubSecretsQ.error} />
      ) : (
        <SecretsBlock
          title="Секреты publish"
          scope="publish"
          items={pubSecretsQ.data?.items ?? []}
          knownKeys={PUBLISH_SECRET_KEYS}
          hint="instagram.default_access_token и ключи S3 подхватываются при следующей операции, перезапуск module-publish не нужен."
        />
      )}
      {reviewSecretsQ.isError ? (
        <QueryError title="Секреты review" error={reviewSecretsQ.error} />
      ) : (
        <SecretsBlock
          title="Секреты review"
          scope="review"
          items={reviewSecretsQ.data?.items ?? []}
          knownKeys={REVIEW_SECRET_KEYS}
          hint="После смены telegram.bot_token нужен перезапуск module-review. Ключи S3 подхватываются без перезапуска."
        />
      )}
      {videoQ.isError ? <QueryError title="Креды video" error={videoQ.error} /> : <VideoCredsBlock items={videoQ.data ?? []} />}
    </Stack>
  );
}

function AccountsTable({ accounts }: { accounts: Account[] }) {
  const qc = useQueryClient();
  const [tokenTarget, setTokenTarget] = useState<Account | null>(null);
  const [editTarget, setEditTarget] = useState<Account | "new" | null>(null);
  const [token, setToken] = useState("");
  const [form, setForm] = useState<AccountWriteBody>({ channel_id: "itim", platform: "instagram", enabled: true });

  const invalidate = async () => qc.invalidateQueries({ queryKey: ["publish", "accounts"] });

  const tokenMut = useMutation({
    mutationFn: async () => {
      if (!tokenTarget?.id) {
        throw new ProblemError({ title: "Не выбран аккаунт" }, 400);
      }
      await api.PUT("/api/v1/publish/accounts/{id}/token", {
        params: { path: { id: tokenTarget.id } },
        body: { access_token: token },
      });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Токен записан", message: "Значение не отображается, только признак «задан»." });
      setTokenTarget(null);
      setToken("");
      await invalidate();
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  const saveMut = useMutation({
    mutationFn: async () => {
      const body: AccountWriteBody = {
        channel_id: form.channel_id?.trim(),
        platform: form.platform?.trim(),
        handle: form.handle?.trim() || undefined,
        external_id: form.external_id?.trim() || undefined,
        enabled: form.enabled,
      };
      if (form.access_token?.trim()) {
        body.access_token = form.access_token.trim();
      }
      if (editTarget === "new") {
        if (!body.channel_id || !body.platform) {
          throw new ProblemError({ title: "Нужны канал и платформа" }, 400);
        }
        await api.POST("/api/v1/publish/accounts", {
          body: { ...body, channel_id: body.channel_id, platform: body.platform },
        });
        return;
      }
      if (!editTarget?.id) {
        throw new ProblemError({ title: "Не выбран аккаунт" }, 400);
      }
      await api.PATCH("/api/v1/publish/accounts/{id}", {
        params: { path: { id: editTarget.id } },
        body,
      });
    },
    onSuccess: async () => {
      notifications.show({
        color: "green",
        title: editTarget === "new" ? "Аккаунт создан" : "Аккаунт обновлён",
        message: "Токен, если задавался, не отображается.",
      });
      setEditTarget(null);
      setForm({ channel_id: "itim", platform: "instagram", enabled: true });
      await invalidate();
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  const openCreate = () => {
    setForm({ channel_id: "itim", platform: "instagram", handle: "", external_id: "", enabled: true, access_token: "" });
    setEditTarget("new");
  };
  const openEdit = (a: Account) => {
    setForm({
      channel_id: a.channel_id ?? "",
      platform: a.platform ?? "",
      handle: a.handle ?? "",
      external_id: a.external_id ?? "",
      enabled: a.enabled !== false,
      access_token: "",
    });
    setEditTarget(a);
  };

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={4}>Аккаунты публикации</Title>
        <Button size="xs" onClick={openCreate}>
          Добавить аккаунт
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        Токен и external_id можно задать при создании или через «Изменить». Новые значения читаются при следующей публикации, перезапуск не нужен.
      </Text>
      <Paper withBorder>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Канал</Table.Th>
              <Table.Th>Платформа</Table.Th>
              <Table.Th>Handle</Table.Th>
              <Table.Th>external_id</Table.Th>
              <Table.Th>Токен</Table.Th>
              <Table.Th>Включён</Table.Th>
              <Table.Th>Обновлён</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {accounts.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={8}>
                  <Text c="dimmed">Аккаунтов нет.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              accounts.map((a) => (
                <Table.Tr key={String(a.id)}>
                  <Table.Td>{a.channel_id ?? "—"}</Table.Td>
                  <Table.Td>{a.platform ?? "—"}</Table.Td>
                  <Table.Td>{a.handle ?? "—"}</Table.Td>
                  <Table.Td>{a.external_id || "—"}</Table.Td>
                  <Table.Td>
                    <Badge color={a.has_token ? "green" : "gray"} variant="light">
                      {setLabel(a.has_token)}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{a.enabled === false ? "выкл" : "вкл"}</Table.Td>
                  <Table.Td>{formatDateTime(a.updated_at)}</Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <Button size="xs" variant="light" onClick={() => openEdit(a)}>
                        Изменить
                      </Button>
                      <Button
                        size="xs"
                        variant="light"
                        onClick={() => {
                          setToken("");
                          setTokenTarget(a);
                        }}
                      >
                        Задать токен
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
        opened={tokenTarget !== null}
        onClose={() => {
          setTokenTarget(null);
          setToken("");
        }}
        title="Записать токен аккаунта"
        message={`Значение не будет показано в интерфейсе. Аккаунт: ${tokenTarget?.handle ?? tokenTarget?.id ?? ""}.`}
        confirmLabel="Сохранить токен"
        reasonRequired={false}
        loading={tokenMut.isPending}
        extra={
          <PasswordInput
            label="Access token"
            value={token}
            onChange={(e) => setToken(e.currentTarget.value)}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            visible={false}
          />
        }
        onConfirm={() => {
          if (!token.trim()) {
            notifications.show({ color: "yellow", title: "Нужен токен", message: "Поле токена пустое." });
            return;
          }
          tokenMut.mutate();
        }}
      />
      <ConfirmAction
        opened={editTarget !== null}
        onClose={() => setEditTarget(null)}
        title={editTarget === "new" ? "Новый аккаунт" : "Изменить аккаунт"}
        message="Токен — поле только для записи. Оставьте пустым, чтобы не менять текущий. Значение в интерфейсе не появится."
        confirmLabel="Сохранить"
        reasonRequired={false}
        loading={saveMut.isPending}
        extra={
          <Stack gap="sm">
            <TextInput
              label="Канал"
              value={form.channel_id ?? ""}
              onChange={(e) => {
                const channel_id = e.currentTarget.value;
                setForm((f) => ({ ...f, channel_id }));
              }}
              required
              autoComplete="off"
            />
            <TextInput
              label="Платформа"
              value={form.platform ?? ""}
              onChange={(e) => {
                const platform = e.currentTarget.value;
                setForm((f) => ({ ...f, platform }));
              }}
              required
              autoComplete="off"
            />
            <TextInput
              label="Handle"
              value={form.handle ?? ""}
              onChange={(e) => {
                const handle = e.currentTarget.value;
                setForm((f) => ({ ...f, handle }));
              }}
              autoComplete="off"
            />
            <TextInput
              label="external_id"
              description="ID аккаунта в Instagram (не секрет)"
              value={form.external_id ?? ""}
              onChange={(e) => {
                const external_id = e.currentTarget.value;
                setForm((f) => ({ ...f, external_id }));
              }}
              autoComplete="off"
            />
            <Checkbox
              label="Включён"
              checked={form.enabled !== false}
              onChange={(e) => {
                const enabled = e.currentTarget.checked;
                setForm((f) => ({ ...f, enabled }));
              }}
            />
            <PasswordInput
              label={editTarget === "new" ? "Токен доступа (необязательно)" : "Новый токен (оставьте пустым, чтобы не менять)"}
              value={form.access_token ?? ""}
              onChange={(e) => {
                const access_token = e.currentTarget.value;
                setForm((f) => ({ ...f, access_token }));
              }}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              visible={false}
            />
          </Stack>
        }
        onConfirm={() => saveMut.mutate()}
      />
    </Stack>
  );
}

function SecretsBlock({
  title,
  scope,
  items,
  knownKeys,
  hint,
}: {
  title: string;
  scope: "publish" | "review";
  items: SecretMeta[];
  knownKeys: readonly string[];
  hint?: string;
}) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [delKey, setDelKey] = useState<string | null>(null);
  const [writeKey, setWriteKey] = useState<string | null>(null);
  const [writeValue, setWriteValue] = useState("");
  const rows = mergeKnownSecrets(knownKeys, items);

  const put = useMutation({
    mutationFn: async (input: { key: string; value: string }) => {
      const path = scope === "publish" ? "/api/v1/publish/secrets/{key}" : "/api/v1/review/secrets/{key}";
      await (api.PUT as (url: string, init: object) => Promise<unknown>)(path, {
        params: { path: { key: input.key } },
        body: { value: input.value },
      });
    },
    onSuccess: async (_data, input) => {
      notifications.show({ color: "green", title: "Секрет записан", message: `${input.key}: значение скрыто, в списке только статус.` });
      setValue("");
      setWriteValue("");
      setWriteKey(null);
      await qc.invalidateQueries({ queryKey: [scope, "secrets"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });
  const del = useMutation({
    mutationFn: async (k: string) => {
      const path = scope === "publish" ? "/api/v1/publish/secrets/{key}" : "/api/v1/review/secrets/{key}";
      await (api.DELETE as (url: string, init: object) => Promise<unknown>)(path, { params: { path: { key: k } } });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Секрет удалён", message: delKey ?? "" });
      setDelKey(null);
      await qc.invalidateQueries({ queryKey: [scope, "secrets"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  return (
    <Stack gap="sm">
      <Title order={4}>{title}</Title>
      {hint ? (
        <Text size="sm" c="dimmed">
          {hint}
        </Text>
      ) : null}
      <Paper withBorder p="md">
        <Group align="flex-end" mb="md">
          <TextInput label="Другой ключ" value={key} onChange={(e) => setKey(e.currentTarget.value)} autoComplete="off" style={{ flex: 1 }} />
          <PasswordInput
            label="Значение"
            value={value}
            onChange={(e) => setValue(e.currentTarget.value)}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            style={{ flex: 1 }}
          />
          <Button onClick={() => put.mutate({ key: key.trim(), value })} loading={put.isPending} disabled={!key.trim() || !value.trim()}>
            Записать
          </Button>
        </Group>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Ключ</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>Обновлён</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((s) => (
              <Table.Tr key={String(s.key)}>
                <Table.Td>{s.key}</Table.Td>
                <Table.Td>
                  <Badge color={s.present ? "green" : "gray"} variant="light">
                    {setLabel(s.present)}
                  </Badge>
                </Table.Td>
                <Table.Td>{formatDateTime(s.updated_at)}</Table.Td>
                <Table.Td>
                  <Group gap="xs" justify="flex-end">
                    <Button
                      size="xs"
                      variant="light"
                      onClick={() => {
                        setWriteValue("");
                        setWriteKey(String(s.key));
                      }}
                    >
                      {s.present ? "Заменить" : "Задать"}
                    </Button>
                    {s.present ? (
                      <Button size="xs" color="red" variant="light" onClick={() => setDelKey(String(s.key))}>
                        Удалить
                      </Button>
                    ) : null}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
      <ConfirmAction
        opened={writeKey !== null}
        onClose={() => {
          setWriteKey(null);
          setWriteValue("");
        }}
        title={items.some((i) => i.key === writeKey && i.present) ? `Заменить ${writeKey}` : `Задать ${writeKey}`}
        message="Значение не будет показано в интерфейсе и не попадёт в журнал."
        confirmLabel="Сохранить"
        reasonRequired={false}
        loading={put.isPending}
        extra={
          <PasswordInput
            label="Значение"
            value={writeValue}
            onChange={(e) => setWriteValue(e.currentTarget.value)}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            visible={false}
          />
        }
        onConfirm={() => {
          if (!writeKey || !writeValue.trim()) {
            notifications.show({ color: "yellow", title: "Нужно значение", message: "Поле пустое." });
            return;
          }
          put.mutate({ key: writeKey, value: writeValue });
        }}
      />
      <ConfirmAction
        opened={delKey !== null}
        onClose={() => setDelKey(null)}
        title="Удалить секрет"
        message={`Удалить ключ ${delKey}? Значение будет стёрто.`}
        confirmLabel="Удалить"
        loading={del.isPending}
        onConfirm={() => delKey && del.mutate(delKey)}
      />
    </Stack>
  );
}

const VIDEO_KINDS = [
  { value: "claude_oauth_token", label: "claude_oauth_token" },
  { value: "anthropic_api_key", label: "anthropic_api_key" },
];

function VideoCredsBlock({ items }: { items: VideoCred[] }) {
  const qc = useQueryClient();
  const [ref, setRef] = useState("CLAUDE_OAUTH_TOKEN");
  const [kind, setKind] = useState("claude_oauth_token");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [delRef, setDelRef] = useState<string | null>(null);
  const put = useMutation({
    mutationFn: async () => {
      await (api.PUT as (url: string, init: object) => Promise<unknown>)("/api/v1/video/credentials/{ref}", {
        params: { path: { ref } },
        body: { kind, value, note: note || undefined },
      });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Кред записан", message: `${ref}: значение скрыто.` });
      setValue("");
      await qc.invalidateQueries({ queryKey: ["video", "credentials"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });
  const del = useMutation({
    mutationFn: async (r: string) => {
      await (api.DELETE as (url: string, init: object) => Promise<unknown>)("/api/v1/video/credentials/{ref}", {
        params: { path: { ref: r } },
      });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Кред удалён", message: delRef ?? "" });
      setDelRef(null);
      await qc.invalidateQueries({ queryKey: ["video", "credentials"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  return (
    <Stack gap="sm">
      <Title order={4}>Креды module-video</Title>
      <Text size="sm" c="dimmed">
        Показаны только «задан» / «не задан» и время обновления. Значения API не возвращает.
      </Text>
      <Paper withBorder p="md">
        <Group align="flex-end" mb="md">
          <TextInput label="ref (CAPITAL_SNAKE)" value={ref} onChange={(e) => setRef(e.currentTarget.value)} autoComplete="off" />
          <Select label="kind" data={VIDEO_KINDS} value={kind} onChange={(v) => setKind(v ?? kind)} allowDeselect={false} />
          <PasswordInput
            label="Значение"
            value={value}
            onChange={(e) => setValue(e.currentTarget.value)}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            style={{ flex: 1 }}
          />
          <TextInput label="Заметка" value={note} onChange={(e) => setNote(e.currentTarget.value)} autoComplete="off" />
          <Button onClick={() => put.mutate()} loading={put.isPending} disabled={!ref.trim() || value.trim().length < 8}>
            Записать
          </Button>
        </Group>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>ref</Table.Th>
              <Table.Th>kind</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>Заметка</Table.Th>
              <Table.Th>Кто обновил</Table.Th>
              <Table.Th>Обновлён</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={7}>
                  <Text c="dimmed">Кредов нет.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              items.map((c) => (
                <Table.Tr key={String(c.ref)}>
                  <Table.Td>{c.ref}</Table.Td>
                  <Table.Td>{c.kind}</Table.Td>
                  <Table.Td>
                    <Badge color="green" variant="light">
                      задан
                    </Badge>
                  </Table.Td>
                  <Table.Td>{c.note || "—"}</Table.Td>
                  <Table.Td>{c.updated_by || "—"}</Table.Td>
                  <Table.Td>{formatDateTime(c.updated_at)}</Table.Td>
                  <Table.Td>
                    <Button size="xs" color="red" variant="light" onClick={() => setDelRef(String(c.ref))}>
                      Удалить
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      <ConfirmAction
        opened={delRef !== null}
        onClose={() => setDelRef(null)}
        title="Удалить кред"
        message={`Удалить ${delRef}? Значение будет стёрто и больше не вернётся в API.`}
        confirmLabel="Удалить"
        loading={del.isPending}
        onConfirm={() => delRef && del.mutate(delRef)}
      />
    </Stack>
  );
}
