"use client";

import { useEffect, useRef } from "react";

/**
 * Reveals its children once, when they first scroll into view.
 *
 * An IntersectionObserver flipping one attribute, with the transition living
 * in CSS — which means it costs nothing on the main thread and disappears
 * entirely under `prefers-reduced-motion`, where the stylesheet simply shows
 * the content.
 */
export function Reveal({ children, className = "", delay = 0, as: Tag = "div" }) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          node.dataset.seen = "true";
          observer.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -60px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag
      ref={ref}
      className={`reveal-on-scroll ${className}`}
      style={{ "--i": delay }}
    >
      {children}
    </Tag>
  );
}
