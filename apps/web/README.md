# @dynamis/web — DynamisData Performance Laboratory

Desktop-first coordinated scientific workbench over the DynamisData serving API.
The design and interaction authority is the RES-101 locked document
("Dynamis Instrument" design system), and this package implements it: fixed
viewport shell, URL-owned durable analysis context, transient playhead state,
specialized renderers per modality and provenance-first inspection.

## Commands

```bash
pnpm install --frozen-lockfile     # from the repository root
pnpm --filter @dynamis/web run dev # Vite dev server, proxies /api to :8000
pnpm --filter @dynamis/web run build
pnpm --filter @dynamis/web run typecheck
pnpm --filter @dynamis/web run lint
pnpm --filter @dynamis/web run test
pnpm --filter @dynamis/web run api:generate  # regenerate src/api/schema.d.ts
pnpm --filter @dynamis/web run api:check     # fail on API schema drift (CI)
```

Run the API first (`uv run dynamis-serve`) and, if the API schema changed,
regenerate the document with `uv run dynamis-openapi` before regenerating the
TypeScript schema.

## State ownership

| state | owner |
| --- | --- |
| durable analysis context (dataset, session, trial, subject, stream, metric, time, range, view, comparison) | URL / TanStack Router (`src/lib/search.ts`) |
| server state (catalog, explorer, metrics, provenance, quality, rights, dense windows) | TanStack Query (`src/lib/api/queries.ts`) |
| transient playhead/hover/brush/selection | Zustand (`src/lib/state/analysis.ts`) |
| presentation-only state (menus, focus mode, theme) | component state / `src/lib/state/ui.ts` |

`t_rel_ns` is the canonical time authority. URL time is decimal nanosecond text;
renderers convert to bounded millisecond offsets from a viewport origin and
convert selections back to exact nanoseconds (`src/lib/time.ts`). Playback never
writes the URL; the laboratory context commits on pause/step/click/navigation.

## Rules that are not negotiable

- The UI never smoothes, interpolates, fuses pose and tracking, recomputes
  production metrics from display samples, or upgrades a source/model estimate
  into measurement or ground truth.
- Measurement class and quality always carry text + shape + color
  (`src/components/common/Badges.tsx`), never color alone.
- Every displayed derived value can open its exact methodology and provenance in
  the inspector.
- Unavailable data renders an explicit state, never a zero.
