import { Button, Group, Paper, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import { ProblemError } from "../api/problem";
import { ConfirmAction } from "../components/ConfirmAction";
import { LoadingLabel, QueryError } from "../components/QueryState";
import { diffLines } from "../lib/diff";
import { formatDateTime } from "../lib/format";
import { showProblem } from "../lib/toasts";

type StepRow = {
  step?: string;
  versions?: string[];
  default?: string | null;
  revision?: number;
  sha256?: Record<string, string>;
};
type VersionDoc = {
  step?: string;
  version?: string;
  sha256?: string;
  placeholders?: string[];
  note?: string | null;
  created_by?: string;
  created_at?: string;
  claude_md?: string;
  task_md?: string;
};
type AuditRow = {
  at?: string;
  actor?: string;
  action?: string;
  step?: string;
  version?: string;
  previous_version?: string | null;
  note?: string | null;
};

async function readJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    throw new ProblemError({ title: "Ошибка загрузки промпта", status: res.status }, res.status);
  }
  return (await res.json()) as T;
}

async function getJson<T>(path: "/api/v1/video/prompts" | "/api/v1/video/prompts/audit", signal?: AbortSignal): Promise<T> {
  const { data, response } = await api.GET(path, { signal });
  if (data !== undefined && data !== null) {
    return data as T;
  }
  // openapi-fetch leaves data undefined when the schema has no content; parse the body anyway
  if (response.ok) {
    const clone = response.clone();
    try {
      return (await clone.json()) as T;
    } catch {
      try {
        return (await response.json()) as T;
      } catch {
        /* fall through */
      }
    }
  }
  throw new ProblemError({ title: "Пустой ответ", status: 502 }, 502);
}

export function PromptsPage() {
  const qc = useQueryClient();
  const listQ = useQuery({
    queryKey: ["video", "prompts"],
    queryFn: ({ signal }) => getJson<StepRow[]>("/api/v1/video/prompts", signal),
  });
  const auditQ = useQuery({
    queryKey: ["video", "prompts", "audit"],
    queryFn: ({ signal }) => getJson<AuditRow[]>("/api/v1/video/prompts/audit", signal),
  });

  const steps = listQ.data ?? [];
  const [step, setStep] = useState<string>("");
  const current = steps.find((s) => s.step === step) ?? steps[0];
  const activeStep = current?.step ?? "";
  const versions = current?.versions ?? [];
  const [left, setLeft] = useState<string>("");
  const [right, setRight] = useState<string>("");
  const effectiveLeft = left || current?.default || "";
  const [creating, setCreating] = useState(false);
  const [activateFor, setActivateFor] = useState<string | null>(null);

  const leftQ = useQuery({
    queryKey: ["video", "prompt", activeStep, effectiveLeft],
    enabled: Boolean(activeStep && effectiveLeft),
    queryFn: ({ signal }) =>
      readJson<VersionDoc>(`/api/v1/video/prompts/${encodeURIComponent(activeStep)}/${encodeURIComponent(effectiveLeft)}`, { signal }),
  });
  const rightQ = useQuery({
    queryKey: ["video", "prompt", activeStep, right],
    enabled: Boolean(activeStep && right && right !== effectiveLeft),
    queryFn: ({ signal }) =>
      readJson<VersionDoc>(`/api/v1/video/prompts/${encodeURIComponent(activeStep)}/${encodeURIComponent(right)}`, { signal }),
  });

  if (listQ.isPending) {
    return <LoadingLabel label="Загружаем промпты…" />;
  }
  if (listQ.isError) {
    return <QueryError title="Промпты" error={listQ.error} />;
  }

  const versionOptions = versions.map((v) => ({ value: v, label: v === current?.default ? `${v} (активна)` : v }));

  return (
    <Stack gap="md">
      <div>
        <Title order={2}>Промпты</Title>
        <Text c="dimmed" size="sm">
          Версии шагов module-video: просмотр, diff, создание и активация (If-Match)
        </Text>
      </div>
      <Group align="flex-end">
        <Select
          label="Шаг"
          data={steps.map((s) => ({ value: s.step ?? "", label: `${s.step} · активна ${s.default ?? "—"}` }))}
          value={current?.step ?? null}
          onChange={(v) => {
            setStep(v ?? "");
            setLeft("");
            setRight("");
          }}
          allowDeselect={false}
          style={{ minWidth: 280 }}
        />
        <Select label="Версия A" data={versionOptions} value={effectiveLeft || null} onChange={(v) => setLeft(v ?? "")} allowDeselect={false} />
        <Select label="Версия B (diff)" data={[{ value: "", label: "только A" }, ...versionOptions]} value={right} onChange={(v) => setRight(v ?? "")} />
        <Button variant="light" onClick={() => setCreating(true)} disabled={!activeStep}>
          Новая версия
        </Button>
        <Button
          disabled={!effectiveLeft || effectiveLeft === current?.default}
          onClick={() => setActivateFor(effectiveLeft)}
        >
          Сделать активной
        </Button>
      </Group>
      {current && (
        <Text size="sm" c="dimmed">
          revision {current.revision ?? "—"}
          {effectiveLeft && current.sha256?.[effectiveLeft] ? ` · sha256 ${current.sha256[effectiveLeft].slice(0, 12)}…` : ""}
        </Text>
      )}
      <PromptView left={leftQ.data} right={right && right !== effectiveLeft ? rightQ.data : undefined} leftPending={leftQ.isFetching} rightPending={Boolean(right) && rightQ.isFetching} />
      <CreateVersionForm
        opened={creating}
        step={activeStep}
        onClose={() => setCreating(false)}
        onCreated={async (version) => {
          setCreating(false);
          setLeft(version);
          setRight("");
          await qc.invalidateQueries({ queryKey: ["video", "prompts"] });
        }}
      />
      <ConfirmAction
        opened={activateFor !== null}
        onClose={() => setActivateFor(null)}
        title="Активировать версию"
        message={`Шаг ${activeStep}: сделать активной ${activateFor}? Нужен If-Match revision=${current?.revision ?? 0}.`}
        confirmLabel="Активировать"
        onConfirm={() => {
          void (async () => {
            try {
              await api.PUT("/api/v1/video/prompts/{step}/active", {
                params: { path: { step: activeStep } },
                body: { version: activateFor ?? "" },
                headers: { "If-Match": String(current?.revision ?? 0) },
              });
              notifications.show({ color: "green", title: "Версия активирована", message: `${activeStep}@${activateFor}` });
              setActivateFor(null);
              await qc.invalidateQueries({ queryKey: ["video", "prompts"] });
            } catch (err) {
              showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" });
            }
          })();
        }}
      />
      <Title order={4}>Аудит промптов</Title>
      {auditQ.isError ? (
        <QueryError title="Аудит промптов" error={auditQ.error} />
      ) : (
        <Paper withBorder>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Когда</Table.Th>
                <Table.Th>Кто</Table.Th>
                <Table.Th>Действие</Table.Th>
                <Table.Th>Шаг</Table.Th>
                <Table.Th>Версия</Table.Th>
                <Table.Th>Была</Table.Th>
                <Table.Th>Заметка</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(auditQ.data ?? []).length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={7}>
                    <Text c="dimmed">Записей аудита нет.</Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                (auditQ.data ?? []).map((r, i) => (
                  <Table.Tr key={`${r.at}-${r.step}-${r.version}-${i}`}>
                    <Table.Td>{formatDateTime(r.at)}</Table.Td>
                    <Table.Td>{r.actor ?? "—"}</Table.Td>
                    <Table.Td>{r.action ?? "—"}</Table.Td>
                    <Table.Td>{r.step ?? "—"}</Table.Td>
                    <Table.Td>{r.version ?? "—"}</Table.Td>
                    <Table.Td>{r.previous_version ?? "—"}</Table.Td>
                    <Table.Td>{r.note ?? "—"}</Table.Td>
                  </Table.Tr>
                ))
              )}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
    </Stack>
  );
}

function PromptView({ left, right, leftPending, rightPending }: { left?: VersionDoc; right?: VersionDoc; leftPending: boolean; rightPending: boolean }) {
  if (leftPending || rightPending) {
    return <LoadingLabel label="Загружаем текст версии…" />;
  }
  if (!left) {
    return <Text c="dimmed">Выберите версию A, чтобы посмотреть текст.</Text>;
  }
  if (!right) {
    return (
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">
            claude.md · {left.version}
          </Text>
          <pre style={preStyle}>{left.claude_md || "—"}</pre>
        </Paper>
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">
            task.md · {left.version}
          </Text>
          <pre style={preStyle}>{left.task_md || "—"}</pre>
        </Paper>
      </SimpleGrid>
    );
  }
  return (
    <Stack>
      <Text size="sm">
        Diff {left.version} → {right.version}
        {left.created_by ? ` · A: ${left.created_by}` : ""}
        {right.created_by ? ` · B: ${right.created_by}` : ""}
      </Text>
      <Paper withBorder p="md">
        <Text fw={600} mb="xs">
          claude.md
        </Text>
        <DiffBlock a={left.claude_md ?? ""} b={right.claude_md ?? ""} />
      </Paper>
      <Paper withBorder p="md">
        <Text fw={600} mb="xs">
          task.md
        </Text>
        <DiffBlock a={left.task_md ?? ""} b={right.task_md ?? ""} />
      </Paper>
    </Stack>
  );
}

const preStyle: import("react").CSSProperties = { whiteSpace: "pre-wrap", fontSize: 12, margin: 0, maxHeight: 480, overflow: "auto" };

function DiffBlock({ a, b }: { a: string; b: string }) {
  const lines = useMemo(() => diffLines(a, b), [a, b]);
  return (
    <pre style={{ ...preStyle, fontFamily: "ui-monospace, monospace" }}>
      {lines.map((l, i) => (
        <div
          key={i}
          style={{
            background: l.kind === "add" ? "rgba(0, 160, 80, 0.12)" : l.kind === "del" ? "rgba(200, 40, 40, 0.12)" : undefined,
          }}
        >
          {l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "} {l.text}
        </div>
      ))}
    </pre>
  );
}

function CreateVersionForm({
  opened,
  step,
  onClose,
  onCreated,
}: {
  opened: boolean;
  step: string;
  onClose: () => void;
  onCreated: (version: string) => Promise<void>;
}) {
  const [version, setVersion] = useState("");
  const [claude, setClaude] = useState("");
  const [task, setTask] = useState("");
  const [note, setNote] = useState("");
  const mut = useMutation({
    mutationFn: async () => {
      await api.POST("/api/v1/video/prompts/{step}", {
        params: { path: { step } },
        body: { version, claude_md: claude, task_md: task, note: note || undefined },
      });
      return version;
    },
    onSuccess: async (v) => {
      notifications.show({ color: "green", title: "Версия создана", message: `${step}@${v}` });
      setVersion("");
      setClaude("");
      setTask("");
      setNote("");
      await onCreated(v);
    },
    onError: (err) => showProblem(err instanceof ProblemError ? err.problem : { title: err instanceof Error ? err.message : "Ошибка" }),
  });
  if (!opened) {
    return null;
  }
  return (
    <Paper withBorder p="md">
      <Title order={4} mb="sm">
        Новая версия · {step}
      </Title>
      <Stack>
        <TextInput label="Версия (semver)" value={version} onChange={(e) => setVersion(e.currentTarget.value)} autoComplete="off" />
        <Textarea label="claude.md" value={claude} onChange={(e) => setClaude(e.currentTarget.value)} minRows={8} autosize autoComplete="off" />
        <Textarea label="task.md" value={task} onChange={(e) => setTask(e.currentTarget.value)} minRows={4} autosize autoComplete="off" />
        <TextInput label="Заметка" value={note} onChange={(e) => setNote(e.currentTarget.value)} autoComplete="off" />
        <Group>
          <Button onClick={() => mut.mutate()} loading={mut.isPending} disabled={!version.trim() || !claude.trim()}>
            Создать
          </Button>
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
