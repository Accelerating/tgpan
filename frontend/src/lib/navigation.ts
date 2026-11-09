import { useCallback, useLayoutEffect, useRef } from "react";

/** Capture before changing pages, since hiding content can clamp scrollY. */
export function usePageScroll(page: string) {
  const positions = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const top = positions.current.get(page) || 0;
    const frame = requestAnimationFrame(() => window.scrollTo(0, top));
    return () => cancelAnimationFrame(frame);
  }, [page]);
  return useCallback(
    (reset?: string) => {
      positions.current.set(page, window.scrollY);
      if (reset) positions.current.delete(reset);
    },
    [page],
  );
}
