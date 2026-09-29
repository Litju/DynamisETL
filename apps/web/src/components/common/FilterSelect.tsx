import { Select } from "@base-ui/react/select";
import { Check, ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/cn";

export interface FilterOption {
  readonly value: string;
  readonly label: string;
}

/**
 * Compact filter select on the Base UI primitive (keyboard, typeahead,
 * focus return and ARIA are Base UI's; the look is the instrument's).
 * The empty string is the "any" option.
 */
export function FilterSelect({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  value: string;
  options: readonly FilterOption[];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <Select.Root
      items={options.map((option) => ({ label: option.label, value: option.value }))}
      value={value}
      onValueChange={(next) => onChange(typeof next === "string" ? next : "")}
    >
      <Select.Trigger
        aria-label={label}
        className={cn(
          "flex h-7 min-w-0 items-center gap-2 rounded-control border border-border-subtle bg-surface-1 pl-2.5 pr-1.5 text-[11.5px] text-text-secondary transition-colors duration-quick hover:border-border-strong data-[popup-open]:border-selected-border",
          className,
        )}
      >
        <span className="shrink-0 text-text-faint">{label}</span>
        <Select.Value className="min-w-0 truncate text-text-primary" />
        <Select.Icon className="ml-auto text-text-faint">
          <ChevronsUpDown size={12} aria-hidden="true" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner sideOffset={4} alignItemWithTrigger={false} align="start" className="z-50 outline-none">
          <Select.Popup className="d-overlay d-pop min-w-[var(--anchor-width)] p-1 outline-none">
            <Select.List className="max-h-[min(20rem,var(--available-height))] overflow-y-auto">
              {options.map((option) => (
                <Select.Item
                  key={option.value || "__any"}
                  value={option.value}
                  className="grid cursor-default grid-cols-[0.875rem_1fr] items-center gap-2 rounded-[5px] py-1.5 pl-2 pr-3 text-[12px] text-text-secondary outline-none data-[highlighted]:bg-hover data-[highlighted]:text-text-primary"
                >
                  <Select.ItemIndicator className="col-start-1 text-accent">
                    <Check size={12} aria-hidden="true" />
                  </Select.ItemIndicator>
                  <Select.ItemText className="col-start-2">{option.label}</Select.ItemText>
                </Select.Item>
              ))}
            </Select.List>
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  );
}
