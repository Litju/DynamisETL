import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useCallback, type ComponentProps, type MouseEvent, type ReactNode } from "react";

import type { LinkTarget } from "@/lib/worlds";

let lastCatalogHref: string | null = null;

function validCatalogHref(href: string): string | null {
  try {
    const url = new URL(href, window.location.origin);
    return url.origin === window.location.origin && /^\/data(?:\/|$)/u.test(url.pathname)
      ? `${url.pathname}${url.search}${url.hash}`
      : null;
  } catch {
    return null;
  }
}

export function recordCatalogReturnHref(href: string): void {
  lastCatalogHref = validCatalogHref(href);
}

export function takeCatalogReturnHref(): string | null {
  const href = lastCatalogHref;
  lastCatalogHref = null;
  return href;
}

/**
 * Router link for a typed `LinkTarget` produced by the World/catalog model.
 *
 * `transition` opts a *major* context change (entity → World, World → World)
 * into a native View Transition. Search-only and playback updates never pass
 * it, so an analytical surface is not snapshotted while it is being used.
 */
export function AppLink({
  to: target,
  transition = false,
  children,
  onClick,
  ...rest
}: {
  to: LinkTarget;
  transition?: boolean;
  children: ReactNode;
} & Omit<ComponentProps<"a">, "href" | "children" | "target">) {
  const location = useRouterState({ select: (state) => state.location });
  const sourceHref = /^\/data(?:\/|$)/u.test(location.pathname)
    ? `${location.pathname}${location.searchStr ?? ""}`
    : null;
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (!event.defaultPrevented && sourceHref && target.to === "/lab/$datasetId/$sessionId") {
      recordCatalogReturnHref(sourceHref);
    }
  };
  return (
    <Link
      to={target.to as never}
      params={(target.params ?? {}) as never}
      search={(target.search ?? {}) as never}
      onClick={handleClick}
      viewTransition={transition ? { types: ["context"] } : false}
      {...(rest as Record<string, unknown>)}
    >
      {children}
    </Link>
  );
}

/** Imperative navigation to a typed target (command palette, menus). */
export function useGoTo() {
  const navigate = useNavigate();
  const location = useRouterState({ select: (state) => state.location });
  return useCallback(
    (target: LinkTarget | string, options: { transition?: boolean; replace?: boolean } = {}) => {
      const transition = options.transition ? { types: ["context"] } : false;
      if (/^\/data(?:\/|$)/u.test(location.pathname)) {
        const destination = typeof target === "string" ? target : target.to;
        if (destination.startsWith("/lab/")) {
          recordCatalogReturnHref(`${location.pathname}${location.searchStr ?? ""}`);
        }
      }
      if (typeof target === "string") {
        void navigate({ href: target, viewTransition: transition, replace: options.replace ?? false });
        return;
      }
      void navigate({
        to: target.to as never,
        params: (target.params ?? {}) as never,
        search: (target.search ?? {}) as never,
        viewTransition: transition,
        replace: options.replace ?? false,
      });
    },
    [location.pathname, location.searchStr, navigate],
  );
}
