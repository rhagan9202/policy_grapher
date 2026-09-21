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
  /** Every live observer, so a test can report a *second* size to one. */
  static live: { observer: TestResizeObserver; element: Element }[] = []

  constructor(private readonly callback: ResizeObserverCallback) {}

  report(element: Element, size: { width: number; height: number }): void {
    this.callback(
      [
        {
          target: element,
          contentRect: { ...size } as DOMRectReadOnly,
        } as ResizeObserverEntry,
      ],
      this,
    )
  }

  observe(element: Element): void {
    TestResizeObserver.observed.push(element)
    TestResizeObserver.live.push({ observer: this, element })
    this.report(element, OBSERVED_SIZE)
  }

  unobserve(element: Element): void {
    TestResizeObserver.live = TestResizeObserver.live.filter(
      (entry) => entry.element !== element,
    )
  }

  disconnect(): void {
    TestResizeObserver.live = TestResizeObserver.live.filter(
      (entry) => entry.observer !== this,
    )
  }
}

globalThis.ResizeObserver = TestResizeObserver

export function observedElements(): Element[] {
  return TestResizeObserver.observed
}

export function resetObservedElements(): void {
  TestResizeObserver.observed = []
}

/**
 * Report a new size to everything currently observed.
 *
 * The stub above reports once, on `observe`, which is enough to prove the
 * canvas was measured but cannot exercise anything that happens when a
 * measurement *changes* — a window drag, or crossing the breakpoint where a
 * panel restacks. Those are the cases where a one-shot framing goes stale.
 */
export function reportResize(size: { width: number; height: number }): void {
  for (const { observer, element } of [...TestResizeObserver.live]) {
    observer.report(element, size)
  }
}
