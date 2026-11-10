"use client";
/* A number that counts up when it appears (Aurora theme). */
import { animate, useInView, useMotionValue, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

export function CountUp({ value, duration = 1.1, format }: { value: number; duration?: number; format?: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const reduced = useReducedMotion();
  const mv = useMotionValue(0);
  const [shown, setShown] = useState(reduced ? value : 0);
  useEffect(() => {
    if (!inView) return;
    if (reduced) { setShown(value); return; }
    const c = animate(mv, value, { duration, ease: [0.2, 0.7, 0.2, 1], onUpdate: (v) => setShown(v) });
    return () => c.stop();
  }, [inView, value, duration, reduced, mv]);
  const n = Number.isInteger(value) ? Math.round(shown) : shown;
  return <span ref={ref} className="tabular-nums">{format ? format(n) : n}</span>;
}
