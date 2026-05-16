"use client";

import { useEffect, useState } from "react";

function formatClock(d: Date) {
  const h = d.getHours().toString().padStart(2, "0");
  const m = d.getMinutes().toString().padStart(2, "0");
  return `${h}:${m}`;
}

function formatDateLine(d: Date) {
  const day = d.toLocaleDateString("en-GB", { weekday: "long" }).toUpperCase();
  const dd = d.getDate();
  const month = d.toLocaleDateString("en-GB", { month: "long" }).toUpperCase();
  return `${day} ${dd} ${month}`;
}

export function JarvisClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="pointer-events-none flex flex-col items-center text-white select-none">
      <p
        className="font-orbitron text-5xl font-medium tracking-[0.12em] sm:text-6xl md:text-7xl"
        style={{ textShadow: "0 0 28px rgba(0, 229, 255, 0.35)" }}
      >
        {formatClock(now)}
      </p>
      <p className="font-orbitron mt-2 text-[10px] font-medium tracking-[0.45em] text-white/85 sm:text-[11px]">
        {formatDateLine(now)}
      </p>
    </div>
  );
}
