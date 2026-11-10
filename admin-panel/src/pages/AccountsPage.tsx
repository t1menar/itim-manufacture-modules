import {
  Badge,
  Button,
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
  handle?: string;
  external_id?: string | null;
  enabled?: boolean;
  has_token?: boolean;
};
type SecretMeta = { key?: string; present?: boolean; length?: number; updated_at?: string | null };
type VideoCred = {
  ref?: string;
  kind?: string;
  note?: string | null;
  updated_by?: string | null;
  updated_at?: string | null;
  length?: number;
};

async function getJson<T>(path: "/api/v1/publish/accounts" | "/api/v1/publish/secrets" | "/api/v1/review/secrets" | "/api/v1/video/credentials" | "/api/v1/overview", signal: AbortSignal): Promise<T> {
  const { data } = await api.GET(path, { signal });
  if (data === undefined) {
    throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
  }
  return data as T;
}

function maskLen(n: number | undefined): string {
  if (!n) {
    return "нет значения";
  }
  return `•••• (${n} символов)`;
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
          Значения секретов не показываются — только наличие и длина. Запись и удаление с подтверждением.
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
        <SecretsBlock title="Секреты publish" scope="publish" items={pubSecretsQ.data?.items ?? []} />
      )}
      {reviewSecretsQ.isError ? (
        <QueryError title="Секреты review" error={reviewSecretsQ.error} />
      ) : (
        <SecretsBlock title="Секреты review" scope="review" items={reviewSecretsQ.data?.items ?? []} />
      )}
      {videoQ.isError ? <QueryError title="Креды video" error={videoQ.error} /> : <VideoCredsBlock items={videoQ.data ?? []} />}
    </Stack>
  );
}

function AccountsTable({ accounts }: { accounts: Account[] }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState<Account | null>(null);
  const [token, setToken] = useState("");
  const mut = useMutation({
    mutationFn: async () => {
      if (!target?.id) {
        throw new ProblemError({ title: "Не выбран аккаунт" }, 400);
      }
      await api.PUT("/api/v1/publish/accounts/{id}/token", {
        params: { path: { id: target.id } },
        body: { access_token: token },
      });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Токен записан", message: "Значение не отображается, только признак has_token." });
      setTarget(null);
      setToken("");
      await qc.invalidateQueries({ queryKey: ["publish", "accounts"] });
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });

  return (
    <Stack gap="sm">
      <Title order={4}>Аккаунты публикации</Title>
      <Paper withBorder>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Канал</Table.Th>
              <Table.Th>Платформа</Table.Th>
              <Table.Th>Handle</Table.Th>
              <Table.Th>Токен</Table.Th>
              <Table.Th>Включён</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {accounts.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed">Аккаунтов нет.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              accounts.map((a) => (
                <Table.Tr key={String(a.id)}>
                  <Table.Td>{a.channel_id ?? "—"}</Table.Td>
                  <Table.Td>{a.platform ?? "—"}</Table.Td>
                  <Table.Td>{a.handle ?? "—"}</Table.Td>
                  <Table.Td>
                    <Badge color={a.has_token ? "green" : "gray"} variant="light">
                      {a.has_token ? "задан" : "нет токена"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{a.enabled === false ? "выкл" : "вкл"}</Table.Td>
                  <Table.Td>
                    <Button size="xs" variant="light" onClick={() => { setToken(""); setTarget(a); }}>
                      Задать токен
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      <ConfirmAction
        opened={target !== null}
        onClose={() => { setTarget(null); setToken(""); }}
        title="Записать токен аккаунта"
        message={`Значение не будет показано в интерфейсе. Аккаунт: ${target?.handle ?? target?.id ?? ""}.`}
        confirmLabel="Сохранить токен"
        reasonRequired={false}
        loading={mut.isPending}
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
          mut.mutate();
        }}
      />
    </Stack>
  );
}

function SecretsBlock({ title, scope, items }: { title: string; scope: "publish" | "review"; items: SecretMeta[] }) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [delKey, setDelKey] = useState<string | null>(null);
  const put = useMutation({
    mutationFn: async () => {
      const path = scope === "publish" ? "/api/v1/publish/secrets/{key}" : "/api/v1/review/secrets/{key}";
      await (api.PUT as (url: string, init: object) => Promise<unknown>)(path, { params: { path: { key } }, body: { value } });
    },
    onSuccess: async () => {
      notifications.show({ color: "green", title: "Секрет записан", message: `${key}: значение скрыто, в списке только длина.` });
      setValue("");
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
      <Paper withBorder p="md">
        <Group align="flex-end" mb="md">
          <TextInput label="Ключ" value={key} onChange={(e) => setKey(e.currentTarget.value)} autoComplete="off" style={{ flex: 1 }} />
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
          <Button onClick={() => put.mutate()} loading={put.isPending} disabled={!key.trim() || !value.trim()}>
            Записать
          </Button>
        </Group>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Ключ</Table.Th>
              <Table.Th>Наличие</Table.Th>
              <Table.Th>Маска</Table.Th>
              <Table.Th>Обновлён</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed">Секретов нет.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              items.map((s) => (
                <Table.Tr key={String(s.key)}>
                  <Table.Td>{s.key}</Table.Td>
                  <Table.Td>{s.present ? "есть" : "нет"}</Table.Td>
                  <Table.Td>{maskLen(s.length)}</Table.Td>
                  <Table.Td>{formatDateTime(s.updated_at)}</Table.Td>
                  <Table.Td>
                    <Button size="xs" color="red" variant="light" onClick={() => setDelKey(String(s.key))}>
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
              <Table.Th>Маска</Table.Th>
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
                  <Table.Td>{maskLen(c.length)}</Table.Td>
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
