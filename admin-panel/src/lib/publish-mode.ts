export type PublishMode = "real" | "fake" | "unknown";

export function publishModeFromOverview(data: unknown): { label: string; mode: PublishMode } {
  const rec = asRecord(data);
  const modules = rec.modules;
  const items = Array.isArray(modules) ? modules : Array.isArray(asRecord(modules).items) ? (asRecord(modules).items as unknown[]) : [];
  const pub = items.find((m) => {
    const row = asRecord(m);
    const id = String(row.id ?? "");
    const name = String(row.name ?? "");
    return id === "publish-instagram" || /instagram/i.test(name) || id.startsWith("publish");
  });
  const name = String(asRecord(pub).name ?? "publish");
  if (/\breal\b/i.test(name)) {
    return { label: name, mode: "real" };
  }
  if (/\bfake\b/i.test(name)) {
    return { label: name, mode: "fake" };
  }
  return { label: name, mode: "unknown" };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}
