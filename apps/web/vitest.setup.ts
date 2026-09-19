import "@testing-library/jest-dom/vitest";

// jsdom lacks matchMedia; components read prefers-reduced-motion through it.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// jsdom lacks ResizeObserver; react-resizable-panels measures panels with it.
if (!("ResizeObserver" in globalThis)) {
  class ResizeObserverStub {
    observe(): void {
      // no-op: the shell renders at its default layout in tests
    }
    unobserve(): void {
      // no-op
    }
    disconnect(): void {
      // no-op
    }
  }
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
}

// jsdom does not implement layout scrolling.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => undefined;
}
