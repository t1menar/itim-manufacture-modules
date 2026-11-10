export function formatDateTime(iso: string | undefined | null): string {
  if (!iso) {
    return "—";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return String(iso);
  }
  return d.toLocaleString("ru-RU", { timeZone: "Europe/Stockholm" });
}

export function formatStatus(status: string | undefined | null): string {
  const key = (status ?? "").toLowerCase();
  return STATUS_LABELS[key] ?? status ?? "—";
}

export const STATUS_LABELS: Record<string, string> = {
  running: "идёт",
  done: "готово",
  failed: "ошибка",
  cancelled: "отменено",
  pending: "ожидает",
  in_progress: "в работе",
  producing: "производится",
  in_review: "на ревью",
  revising: "доработка",
  approved: "одобрено",
  publishing: "публикуется",
  published: "опубликовано",
  skipped: "пропущено",
  needs_attention: "нужно внимание",
  queued: "в очереди",
  dispatching: "отправка",
  dispatched: "отправлено",
  succeeded: "успех",
  timed_out: "таймаут",
  draft: "черновик",
  ready: "готово к очереди",
  in_production: "в производстве",
  archived: "архив",
  up: "в сети",
  down: "нет связи",
  unknown: "неизвестно",
};

export function statusColor(status: string | undefined | null): string {
  const key = (status ?? "").toLowerCase();
  if (["running", "producing", "publishing", "dispatching", "dispatched", "in_review", "revising", "queued", "ready"].includes(key)) {
    return "blue";
  }
  if (["done", "succeeded", "published", "approved", "up"].includes(key)) {
    return "green";
  }
  if (["failed", "timed_out", "down"].includes(key)) {
    return "red";
  }
  if (["cancelled", "skipped", "archived"].includes(key)) {
    return "gray";
  }
  if (["needs_attention"].includes(key)) {
    return "orange";
  }
  return "gray";
}
