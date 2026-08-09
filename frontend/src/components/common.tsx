import { useEffect, useRef, useState } from "react";
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

/** Copies text to the clipboard and says so for a moment. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    // navigator.clipboard needs a secure context, which a container reached at
    // a plain-http LAN address is not. The old execCommand still works there.
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const scratch = document.createElement("textarea");
      scratch.value = text;
      scratch.style.position = "fixed";
      scratch.style.opacity = "0";
      document.body.appendChild(scratch);
      scratch.select();
      try {
        document.execCommand("copy");
      } finally {
        document.body.removeChild(scratch);
      }
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button className="subtle" onClick={copy} disabled={!text}>
      {copied ? "Copied" : label}
    </button>
  );
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
