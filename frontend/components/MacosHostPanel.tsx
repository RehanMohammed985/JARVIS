"use client";

import type { MacosProbe } from "@/lib/useJarvisSession";

function statusDot(status: string | undefined) {
  if (status === "ok") return "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.7)]";
  if (status === "warn") return "bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.55)]";
  if (status === "error") return "bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.6)]";
  return "bg-sky-400/70";
}

export function MacosHostPanel({ probe }: { probe: MacosProbe }) {
  const native = probe.native_macos_backend === true;
  const complete = probe.permissions_complete === true;
  const checks = probe.permission_checks ?? [];

  return (
    <div className="rounded-2xl border border-white/12 bg-white/[0.05] backdrop-blur-xl">
      <div className="border-b border-white/10 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`h-2.5 w-2.5 rounded-full ${complete ? "bg-emerald-400" : "bg-amber-400"}`}
            aria-hidden
          />
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-zinc-300">
            macOS host · permissions
          </p>
          {!complete && native ? (
            <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-100">
              Action needed
            </span>
          ) : null}
          {native ? (
            <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-200">
              Native API
            </span>
          ) : null}
          {probe.in_docker ? (
            <span className="rounded-full bg-rose-500/25 px-2 py-0.5 text-[10px] text-rose-100">
              Docker — wrong runtime
            </span>
          ) : null}
        </div>
        {probe.host_python_executable ? (
          <p className="mt-2 font-mono text-[10px] leading-snug text-zinc-500">
            Host Python: <span className="text-zinc-400">{probe.host_python_executable}</span>
          </p>
        ) : null}
        {probe.relaunch_hint ? (
          <p className="mt-2 text-xs leading-snug text-sky-200/85">{probe.relaunch_hint}</p>
        ) : null}
      </div>

      {checks.length > 0 ? (
        <ul className="max-h-52 space-y-2 overflow-y-auto px-4 py-3">
          {checks.map((c) => (
            <li
              key={c.id ?? c.label}
              className="flex gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2 text-left"
            >
              <span
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${statusDot(c.status)}`}
                title={c.status}
              />
              <div>
                <p className="text-xs font-medium text-zinc-200">{c.label}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-zinc-500">{c.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {(probe.warnings?.length ?? 0) > 0 ? (
        <div className="border-t border-amber-500/20 bg-amber-500/[0.06] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-200/90">
            Warnings
          </p>
          <ul className="mt-2 space-y-1.5 text-xs text-amber-50/95">
            {(probe.warnings ?? []).map((w) => (
              <li key={w}>• {w}</li>
            ))}
          </ul>
          {probe.file_actions_native === false ? (
            <p className="mt-2 text-xs text-amber-100/90">
              Set <code className="rounded bg-black/30 px-1">JARVIS_FILE_ACTIONS_MODE=server</code> so
              this Mac runs <code className="px-1">open</code> directly, or keep the file bridge running.
            </p>
          ) : null}
        </div>
      ) : null}

      <details className="group border-t border-white/10 px-4 py-3">
        <summary className="cursor-pointer list-none text-center text-xs font-medium text-sky-300/90 [&::-webkit-details-marker]:hidden">
          <span className="underline-offset-4 group-open:underline">Full macOS setup guide</span>
        </summary>
        <div className="mt-4 space-y-4">
          {(probe.setup_sections ?? []).map((sec) => (
            <div key={sec.id} className="rounded-xl border border-white/8 bg-black/25 px-3 py-3">
              <p className="text-xs font-semibold text-zinc-200">{sec.title}</p>
              <ol className="mt-2 list-decimal space-y-1.5 pl-4 text-[11px] leading-relaxed text-zinc-400">
                {sec.steps.map((s, i) => (
                  <li key={i} className="whitespace-pre-wrap">
                    {s}
                  </li>
                ))}
              </ol>
              {sec.after_save ? (
                <p className="mt-2 text-[10px] text-sky-300/80">{sec.after_save}</p>
              ) : null}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
