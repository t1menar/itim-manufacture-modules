import { Badge } from "@mantine/core";

import { formatStatus, statusColor } from "../lib/format";

export function StatusBadge({ status }: { status?: string | null }) {
  return (
    <Badge variant="light" color={statusColor(status)}>
      {formatStatus(status)}
    </Badge>
  );
}
