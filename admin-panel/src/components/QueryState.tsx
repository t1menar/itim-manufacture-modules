import { Alert, Group, Loader, Stack, Text, Title } from "@mantine/core";

import { formatProblem, ProblemError } from "../api/problem";

export function LoadingLabel({ label }: { label: string }) {
  return (
    <Group gap="sm">
      <Loader size="sm" />
      <Text c="dimmed">{label}</Text>
    </Group>
  );
}

export function QueryError({ title, error }: { title: string; error: unknown }) {
  const msg = error instanceof ProblemError ? formatProblem(error.problem) : error instanceof Error ? error.message : "Неизвестная ошибка";
  return (
    <Stack>
      <Title order={2}>{title}</Title>
      <Alert color="red" title="Не удалось загрузить">
        {msg}
      </Alert>
    </Stack>
  );
}
