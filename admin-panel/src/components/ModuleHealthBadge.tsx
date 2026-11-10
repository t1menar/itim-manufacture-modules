import { Badge } from "@mantine/core";

const LABELS: Record<string, { label: string; color: string }> = {
  up: { label: "в сети", color: "green" },
  down: { label: "нет связи", color: "red" },
  unknown: { label: "неизвестно", color: "gray" },
};

export function ModuleHealthBadge({ health }: { health?: string }) {
  const key = (health ?? "unknown").toLowerCase();
  const spec = LABELS[key] ?? { label: health ?? "неизвестно", color: "gray" };
  return (
    <Badge variant="filled" color={spec.color} leftSection={dot(spec.color)}>
      {spec.label}
    </Badge>
  );
}

function dot(color: string): string {
  // Colour + text (a11y): the badge label already has the word; this is a visual cue.
  return color === "green" ? "●" : color === "red" ? "●" : "○";
}
