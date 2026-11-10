import { Button, Group, Modal, Stack, Text, Textarea } from "@mantine/core";
import { type ReactNode, useState } from "react";

export function ConfirmAction({
  opened,
  onClose,
  title,
  message,
  confirmLabel = "Подтвердить",
  reasonRequired = false,
  withReason = false,
  reasonLabel = "Причина",
  loading = false,
  extra,
  onConfirm,
}: {
  opened: boolean;
  onClose: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  reasonRequired?: boolean;
  withReason?: boolean;
  reasonLabel?: string;
  loading?: boolean;
  extra?: ReactNode;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const showReason = withReason || reasonRequired;
  const can = !reasonRequired || reason.trim().length > 0;
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      onExitTransitionEnd={() => setReason("")}
    >
      <Stack>
        <Text size="sm">{message}</Text>
        {showReason && (
          <Textarea
            label={reasonLabel}
            required={reasonRequired}
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
            minRows={2}
            autoComplete="off"
          />
        )}
        {extra}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={loading}>
            Отмена
          </Button>
          <Button color="red" onClick={() => onConfirm(reason.trim())} disabled={!can} loading={loading}>
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
