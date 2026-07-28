import type { Money } from "../types";

export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];

/** Money always renders with its currency. There is no bare amount in the UI. */
export function Amount({ value, className }: { value: Money | null; className?: string }) {
  if (!value) return <span className="muted">—</span>;
  return (
    <span className={className}>
      {value.amount}
      <span className="currency-tag">{value.currency}</span>
    </span>
  );
}

export function Loading({ what }: { what: string }) {
  return <div className="spinner">Loading {what}…</div>;
}

export function ErrorNotice({ message }: { message: string }) {
  return <div className="notice error">{message}</div>;
}

export function formatCondition(condition: string) {
  return condition.replace(/_/g, " ").toLowerCase();
}

export function formatDays(days: number | null | undefined) {
  if (days == null) return "unknown";
  if (days < 1 / 24) return "just now";
  if (days < 1) return `${Math.round(days * 24)} hours ago`;
  if (days < 2) return "yesterday";
  return `${Math.round(days)} days ago`;
}
