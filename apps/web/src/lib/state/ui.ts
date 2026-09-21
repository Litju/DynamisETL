/**
 * Small UI preferences and ephemeral shell state.
 *
 * Theme and focus mode are presentation concerns only; they never carry
 * analytical context. Only the theme preference is persisted, validated with
 * Zod on read.
 */

import { create } from "zustand";
import { z } from "zod";

export type Theme = "dark" | "light";

const THEME_KEY = "dynamis.theme";
const themeSchema = z.enum(["dark", "light"]);

export function readStoredTheme(storage?: Storage): Theme {
  try {
    const parsed = themeSchema.safeParse((storage ?? globalThis.localStorage)?.getItem(THEME_KEY));
    return parsed.success ? parsed.data : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  root.dataset.theme = theme;
}

export interface UiState {
  paletteOpen: boolean;
  focusMode: boolean;
  theme: Theme;
  /**
   * Explicit inspector override. `null` follows the route's own rule: the
   * evidence pane expands where a selection can be inspected and compacts to a
   * rail elsewhere, so an empty inspector never reserves flagship width.
   */
  inspectorOpen: boolean | null;
  setPaletteOpen: (open: boolean) => void;
  toggleFocusMode: () => void;
  setTheme: (theme: Theme) => void;
  setInspectorOpen: (open: boolean | null) => void;
}

/** Resolve inspector visibility from the route default and any user override. */
export function inspectorVisible(override: boolean | null, routeDefault: boolean): boolean {
  return override ?? routeDefault;
}

export const useUiStore = create<UiState>()((set) => ({
  paletteOpen: false,
  focusMode: false,
  theme: readStoredTheme(),
  inspectorOpen: null,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  toggleFocusMode: () => set((state) => ({ focusMode: !state.focusMode })),
  setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
  setTheme: (theme) => {
    try {
      globalThis.localStorage?.setItem(THEME_KEY, theme);
    } catch {
      // Storage may be unavailable (private mode); the in-memory theme still applies.
    }
    applyTheme(theme);
    set({ theme });
  },
}));
