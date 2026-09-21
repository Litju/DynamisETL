import { Dialog } from "@base-ui/react/dialog";
import { useNavigate } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";

import { cn } from "@/lib/cn";
import { useAnalysisStore } from "@/lib/state/analysis";
import { useUiStore } from "@/lib/state/ui";
import { formatNsDecimal } from "@/lib/time";

export interface Command {
  readonly id: string;
  readonly title: string;
  readonly group: string;
  readonly run: () => void;
}

export function filterCommands(commands: readonly Command[], query: string): Command[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...commands];
  return commands.filter(
    (command) =>
      command.title.toLowerCase().includes(needle) || command.group.toLowerCase().includes(needle),
  );
}

/**
 * Cmd/Ctrl+K command palette. Commands are navigation/selection intents only;
 * scientific computation is never triggered from here.
 */
export function CommandPalette() {
  const open = useUiStore((state) => state.paletteOpen);
  const setOpen = useUiStore((state) => state.setPaletteOpen);
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  const toggleFocusMode = useUiStore((state) => state.toggleFocusMode);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const setPlaying = useAnalysisStore((state) => state.setPlaying);
  const setBrushRange = useAnalysisStore((state) => state.setBrushRange);
  const resetTransient = useAnalysisStore((state) => state.resetTransient);

  const commands = useMemo<Command[]>(
    () => [
      {
        id: "go-catalog",
        title: "Go to Catalog",
        group: "Navigate",
        run: () => void navigate({ to: "/catalog" }),
      },
      {
        id: "go-runs",
        title: "Go to Processing runs",
        group: "Navigate",
        run: () => void navigate({ to: "/runs" }),
      },
      {
        id: "go-methods",
        title: "Go to Methodology",
        group: "Navigate",
        run: () => void navigate({ to: "/methods" }),
      },
      {
        id: "go-quality",
        title: "Go to Quality & Rights",
        group: "Navigate",
        run: () => void navigate({ to: "/quality" }),
      },
      {
        id: "go-compare",
        title: "Go to Compare",
        group: "Navigate",
        run: () => void navigate({ to: "/compare" }),
      },
      {
        id: "toggle-theme",
        title: theme === "dark" ? "Switch to Report Light" : "Switch to Instrument Dark",
        group: "View",
        run: () => setTheme(theme === "dark" ? "light" : "dark"),
      },
      { id: "focus-panel", title: "Toggle focus mode", group: "View", run: toggleFocusMode },
      {
        id: "play-pause",
        title: "Play/pause playback",
        group: "Transport",
        run: () => setPlaying(!useAnalysisStore.getState().playing),
      },
      {
        id: "reset-transient",
        title: "Clear ephemeral selection",
        group: "Transport",
        run: () => {
          setBrushRange(null);
          resetTransient();
        },
      },
      {
        id: "copy-time",
        title: "Copy current committed time",
        group: "Transport",
        run: () => {
          const time = useAnalysisStore.getState().committedTimeNs;
          if (time !== null) {
            void navigator.clipboard?.writeText(formatNsDecimal(time));
          }
        },
      },
    ],
    [navigate, resetTransient, setBrushRange, setPlaying, setTheme, theme, toggleFocusMode],
  );

  const visible = useMemo(() => filterCommands(commands, query), [commands, query]);
  const active = Math.min(activeIndex, Math.max(0, visible.length - 1));

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setQuery("");
      setActiveIndex(0);
    }
    setOpen(next);
  };

  const runCommand = (command: Command | undefined) => {
    if (!command) return;
    command.run();
    setOpen(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Popup
          aria-label="Command palette"
          className="fixed left-1/2 top-24 z-50 w-[36rem] max-w-[90vw] -translate-x-1/2 overflow-hidden rounded-panel border border-border-strong bg-surface-2 shadow-overlay"
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <input
            ref={inputRef}
            value={query}
            autoFocus
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex(Math.min(active + 1, visible.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex(Math.max(active - 1, 0));
              } else if (event.key === "Enter") {
                event.preventDefault();
                runCommand(visible[active]);
              }
            }}
            placeholder="Type a command or search"
            aria-label="Command search"
            aria-controls="command-list"
            aria-activedescendant={
              visible[active]?.id ? `command-option-${visible[active].id}` : undefined
            }
            className="w-full border-b border-border-subtle bg-transparent px-3 py-2 text-[13px] outline-none placeholder:text-text-muted"
          />
          <ul
            id="command-list"
            role="listbox"
            aria-label="Commands"
            className="max-h-80 overflow-y-auto p-1"
          >
            {visible.length === 0 ? (
              <li className="px-2 py-3 text-[12px] text-text-muted">No matching command.</li>
            ) : null}
            {visible.map((command, index) => (
              <li
                id={`command-option-${command.id}`}
                key={command.id}
                role="option"
                aria-selected={index === active}
                tabIndex={-1}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => runCommand(command)}
                className={cn(
                  "flex w-full cursor-pointer items-center justify-between rounded-control px-2 py-1.5 text-left text-[12px]",
                  index === active ? "bg-surface-3 text-text-primary" : "text-text-secondary",
                )}
              >
                <span>{command.title}</span>
                <span className="t-section text-text-muted">{command.group}</span>
              </li>
            ))}
          </ul>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
