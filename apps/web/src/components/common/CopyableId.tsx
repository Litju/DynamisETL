import { Check, Copy } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/cn";

/**
 * Exact machine identity as a secondary evidence layer.
 *
 * Internal ids, checksums and code revisions stay inspectable and copyable, but
 * they are not the primary visual language: the human-readable name leads and
 * this renders the exact value underneath it, truncated with the full text
 * available through the title attribute and the clipboard.
 */
export function CopyableId({
  value,
  label,
  className,
  truncate = true,
}: {
  value: string;
  /** Accessible description, e.g. "dataset id". */
  label: string;
  className?: string;
  truncate?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = useCallback(() => {
    void navigator.clipboard
      ?.writeText(value)
      .then(() => {
        setCopied(true);
        if (timer.current !== null) window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setCopied(false), 1400);
      })
      .catch(() => {
        // Clipboard access can be denied; the value stays visible and
        // selectable, so no fallback state is needed.
      });
  }, [value]);

  return (
    <span className={cn("group/id inline-flex min-w-0 items-center gap-1", className)}>
      <span
        className={cn("mono text-[11px] text-text-muted", truncate && "truncate")}
        title={value}
      >
        {value}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? `${label} copied` : `Copy ${label}`}
        title={`Copy ${label}`}
        className="shrink-0 rounded-[3px] p-0.5 text-text-muted opacity-0 transition-opacity duration-quick hover:bg-surface-2 hover:text-text-secondary focus-visible:opacity-100 group-hover/id:opacity-100"
      >
        {copied ? (
          <Check size={11} aria-hidden="true" className="text-quality-valid" />
        ) : (
          <Copy size={11} aria-hidden="true" />
        )}
      </button>
    </span>
  );
}
