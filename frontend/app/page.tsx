/* eslint-disable @next/next/no-img-element */
"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { HUD } from "@/components/HUD";
import { useJarvisSession } from "@/lib/useJarvisSession";

const Hologram = dynamic(
  () => import("@/components/HologramOrb").then((m) => m.HologramOrb),
  {
    ssr: false,
    loading: () => (
      <div
        className="mx-auto max-w-full bg-transparent"
        style={{
          width: `min(80vw, min(54vh, 640px))`,
          aspectRatio: "1",
        }}
        aria-hidden
      />
    ),
  },
);

function useClock(tick = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), tick);
    return () => clearInterval(id);
  }, [tick]);
  return now;
}

/** Fixed column widths so `//` aligns like the mock (monospace). */
function LockStatusRows({
  connected,
  backendHealth,
}: {
  connected: boolean;
  backendHealth: string | null;
}) {
  const healthy = connected && backendHealth && backendHealth !== "offline";

  const system = healthy ? "ONLINE" : connected ? "DEGRADED" : "OFFLINE";
  const voice = connected ? "ACTIVE" : "STANDBY";
  const network = connected ? "SECURE" : "OPEN";
  const power = "OPTIMAL";

  const rows: { label: string; value: string }[] = [
    { label: "SYSTEM STATUS", value: system },
    { label: "VOICE STATUS", value: voice },
    { label: "NETWORK", value: network },
    { label: "POWER", value: power },
  ];

  return (
    <div className="jarvis-lock-status-grid">
      {rows.map(({ label, value }) => (
        <div key={label} className="flex items-baseline">
          <span
            className="inline-block w-[13.5ch] shrink-0 sm:w-[14.5ch]"
            style={{ color: "var(--jarvis-label)" }}
          >
            {label}
          </span>
          <span className="shrink-0 text-white/[0.38]">{"//"}</span>
          <span className="pl-1 font-medium tracking-[0.12em] text-white">{value}</span>
        </div>
      ))}
    </div>
  );
}

export default function Page() {
  const session = useJarvisSession();
  const now = useClock(1000);

  const timeStr = useMemo(
    () =>
      now.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [now],
  );

  const dateCaps = useMemo(() => {
    const weekday = now.toLocaleDateString(undefined, { weekday: "long" }).toUpperCase();
    const month = now.toLocaleDateString(undefined, { month: "long" }).toUpperCase();
    const day = now.getDate();
    const year = now.getFullYear();
    return `${weekday} ${month} ${day} ${year}`;
  }, [now]);

  return (
    <main
      className="relative min-h-[100dvh] overflow-hidden text-white"
      style={{ backgroundColor: "#02040a" }}
    >
      <div className="jarvis-lock-vignette" aria-hidden />

      {/* Upper-center hero stack like reference art */}
      <div className="relative z-10 flex min-h-[100dvh] flex-col items-center px-5 pt-[max(2.5rem,min(10.5vh,6.25rem))] sm:px-8">
        <div className="flex w-full max-w-[min(96vw,36rem)] flex-col items-center">
          <Hologram phase={session.phase} speaking={session.phase === "speaking"} />

          <div className="mt-7 flex w-full flex-col items-center text-center sm:mt-9">
            <p
              className="font-exo text-[clamp(2.85rem,10.5vw,5.5rem)] font-thin tabular-nums leading-none tracking-[0.045em] text-white"
              suppressHydrationWarning
            >
              {timeStr}
            </p>
            <p
              className="mt-5 w-full max-w-[min(92vw,34rem)] font-exo text-[clamp(5.25px,1.05vw,7.75px)] font-extralight uppercase leading-relaxed text-white/58 sm:text-[8px]"
              style={{ letterSpacing: "0.62em" }}
              suppressHydrationWarning
            >
              {dateCaps}
            </p>
          </div>
        </div>
      </div>

      <div className="pointer-events-none fixed bottom-7 left-5 z-20 sm:bottom-9 sm:left-9">
        <LockStatusRows connected={session.connected} backendHealth={session.backendHealth} />
      </div>

      <div className="group/hud fixed bottom-0 right-0 z-[70] flex h-36 w-52 items-end justify-end p-3 sm:h-40 sm:w-60 sm:p-5">
        <div className="pointer-events-none max-md:pointer-events-auto max-md:opacity-100 md:opacity-0 md:transition-opacity md:duration-300 md:group-hover/hud:pointer-events-auto md:group-hover/hud:opacity-100">
          <HUD session={session} placement="corner" />
        </div>
      </div>
    </main>
  );
}
