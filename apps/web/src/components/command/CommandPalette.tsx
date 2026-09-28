import { Dialog } from "@base-ui/react/dialog";
import { lazy, Suspense, useEffect } from "react";

import { useUiStore } from "@/lib/state/ui";

// The searchable body (Base UI Autocomplete + catalog search) loads on the
// first open, so the entry shell never pays for it.
const PaletteBody = lazy(() => import("@/components/command/PaletteBody").then((module) => ({ default: module.PaletteBody })));

export interface Command {
  readonly id: string;
  readonly title: string;
  readonly group: string;
  readonly run: () => void;
}

/** Plain-text command filter (kept for the shell contract tests). */
export function filterCommands(commands: readonly Command[], query: string): Command[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...commands];
  return commands.filter(
    (command) =>
      command.title.toLowerCase().includes(needle) || command.group.toLowerCase().includes(needle),
  );
}

/**
 * Command palette (Ctrl/⌘ K): the first-class navigation surface.
 *
 * Recent contexts, World switching, sections and a metadata-only catalog
 * search. Commands are navigation/selection intents only; no scientific
 * computation or acquisition is ever triggered from here.
 */
export function CommandPalette() {
  const open = useUiStore((state) => state.paletteOpen);
  const setOpen = useUiStore((state) => state.setPaletteOpen);
  useEffect(() => {
    // Warm the palette chunk once the first paint is done, so Ctrl/⌘ K is
    // instant without putting the chunk on the critical path.
    const warm = () => void import("@/components/command/PaletteBody");
    const idle = (globalThis as { requestIdleCallback?: (callback: () => void) => number }).requestIdleCallback;
    if (idle) {
      idle(warm);
      return;
    }
    const timer = globalThis.setTimeout(warm, 1500);
    return () => globalThis.clearTimeout(timer);
  }, []);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Backdrop className="d-backdrop fixed inset-0 z-40" />
        <Dialog.Viewport className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
          <Dialog.Popup
            aria-label="Command palette"
            className="d-overlay d-pop flex max-h-[min(34rem,78vh)] w-[40rem] max-w-full flex-col overflow-hidden outline-none"
          >
            <Dialog.Title className="sr-only">Command palette</Dialog.Title>
            {open ? (
              <Suspense fallback={<div className="h-12 border-b border-border-subtle px-4 py-3.5"><div className="d-skeleton h-4 w-64" /></div>}>
                <PaletteBody onDone={() => setOpen(false)} />
              </Suspense>
            ) : null}
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

