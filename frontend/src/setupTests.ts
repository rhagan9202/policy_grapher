import '@testing-library/jest-dom/vitest'

/**
 * jsdom implements no ResizeObserver, and the absence of one is why a blank
 * graph shipped: `GraphExplorer` measured its canvas container through an
 * observer that, under the old mount-effect, was never constructed at all.
 * Nothing in the suite noticed, because a constructor that is never called
 * cannot be missing.
 *
 * This stub reports a fixed size to whoever observes an element, and records
 * what was observed, so a test can assert the measurement actually reached the
 * component rather than that *some* number did.
 */
export const OBSERVED_SIZE = { width: 800, height: 600 }

class TestResizeObserver implements ResizeObserver {
  static observed: Element[] = []

  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(element: Element): void {
    TestResizeObserver.observed.push(element)
    this.callback(
      [
        {
          target: element,
          contentRect: { ...OBSERVED_SIZE } as DOMRectReadOnly,
        } as ResizeObserverEntry,
      ],
      this,
    )
  }

  unobserve(): void {}

  disconnect(): void {}
}

globalThis.ResizeObserver = TestResizeObserver

export function observedElements(): Element[] {
  return TestResizeObserver.observed
}

export function resetObservedElements(): void {
  TestResizeObserver.observed = []
}
