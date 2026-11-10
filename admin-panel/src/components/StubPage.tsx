import { Alert, Stack, Text, Title } from "@mantine/core";

export function StubPage({ title, hint }: { title: string; hint?: string }) {
  return (
    <Stack gap="md">
      <Title order={2}>{title}</Title>
      <Alert color="gray" title="Экран появится в следующем PR">
        <Text size="sm">
          Каркас панели готов: навигация, тема, клиент admin-api и обработка ошибок уже работают. Содержимое
          этого раздела пока заглушка.
          {hint ? ` ${hint}` : ""}
        </Text>
      </Alert>
    </Stack>
  );
}
