"use client";

import { motion, AnimatePresence } from "framer-motion";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { MacosHostPanel } from "@/components/MacosHostPanel";
import type { JarvisSession } from "@/lib/useJarvisSession";

const modes = [
  { id: "push_to_talk", label: "Voice" },
  { id: "wake_word", label: "Wake" },
  { id: "always_on", label: "Type" },
] as const;

type SpeechRecognitionLike = JarvisSpeechRecognition;

export function HUD({
  session,
  placement = "viewport",
}: {
  session: JarvisSession;
  /** `corner`: relative stack for parent hover zone (lock-screen). */
  placement?: "viewport" | "corner";
}) {
  const [text, setText] = useState("");
  const [micBusy, setMicBusy] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [micHint, setMicHint] = useState<string | null>(null);
  const [showType, setShowType] = useState(false);
  const [showSystem, setShowSystem] = useState(false);

  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const wantListenRef = useRef(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bufRef = useRef("");
  const pausedForJarvisRef = useRef(false);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sendTextRef = useRef(session.sendText);
  sendTextRef.current = session.sendText;
  const unlockRef = useRef(session.unlockAudio);
  unlockRef.current = session.unlockAudio;

  const phaseLabel = useMemo(() => {
    switch (session.phase) {
      case "listening":
        return "Listening";
      case "thinking":
        return "Thinking";
      case "speaking":
        return "Speaking";
      case "tool_running":
        return "Working";
      default:
        return "Ready";
    }
  }, [session.phase]);

  useEffect(() => {
    setMounted(true);
  }, []);

  const speechSupported =
    mounted &&
    typeof window !== "undefined" &&
    ("webkitSpeechRecognition" in window || "SpeechRecognition" in window);

  function clearDebounce() {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
  }

  function clearRestart() {
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
  }

  function stopListening() {
    wantListenRef.current = false;
    pausedForJarvisRef.current = false;
    clearDebounce();
    clearRestart();
    bufRef.current = "";
    const r = recRef.current;
    recRef.current = null;
    if (r) {
      try {
        r.stop();
      } catch {
        /* noop */
      }
    }
    setMicBusy(false);
  }

  function attachRecognition() {
    if (!speechSupported) return;

    const Win = window as typeof window & {
      SpeechRecognition?: new () => SpeechRecognitionLike;
      webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    };
    const SR = Win.SpeechRecognition ?? Win.webkitSpeechRecognition;
    if (!SR) {
      setMicHint("Speech API unavailable.");
      return;
    }

    if (recRef.current) {
      try {
        recRef.current.stop();
      } catch {
        /* noop */
      }
      recRef.current = null;
    }

    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang =
      typeof navigator !== "undefined" && navigator.language?.trim()
        ? navigator.language
        : "en-US";

    rec.onresult = (ev: SpeechRecognitionEvent) => {
      let chunk = "";
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const row = ev.results[i];
        const piece = row[0]?.transcript ?? "";
        if (row.isFinal) {
          chunk += piece;
        } else {
          interim += piece;
        }
      }
      if (interim.trim()) {
        setMicHint(interim.trim().slice(-48));
      }
      if (!chunk.trim()) return;
      bufRef.current = `${bufRef.current} ${chunk}`.trim();
      clearDebounce();
      debounceRef.current = setTimeout(() => {
        const payload = bufRef.current.trim();
        bufRef.current = "";
        debounceRef.current = null;
        if (payload.length >= 2) void sendTextRef.current(payload);
      }, 380);
    };

    rec.onerror = (ev: SpeechRecognitionErrorEvent) => {
      setMicHint(ev.error);
      if (ev.error === "not-allowed") {
        stopListening();
        setShowType(true);
      }
    };

    rec.onend = () => {
      recRef.current = null;
      if (!wantListenRef.current) {
        setMicBusy(false);
        return;
      }
      if (pausedForJarvisRef.current) {
        return;
      }
      clearRestart();
      restartTimerRef.current = setTimeout(() => {
        restartTimerRef.current = null;
        if (
          wantListenRef.current &&
          !pausedForJarvisRef.current &&
          speechSupported
        ) {
          attachRecognition();
        }
      }, 240);
    };

    recRef.current = rec;
    try {
      rec.start();
    } catch {
      setMicHint("Mic start failed");
      wantListenRef.current = false;
      setMicBusy(false);
    }
  }

  async function startListening() {
    await unlockRef.current();
    if (!speechSupported) {
      setMicHint("Use Chrome — or type");
      setShowType(true);
      return;
    }
    setMicHint(null);
    wantListenRef.current = true;
    pausedForJarvisRef.current = false;
    setMicBusy(true);
    attachRecognition();
  }

  useEffect(() => {
    const busy =
      session.phase === "thinking" ||
      session.phase === "speaking" ||
      session.phase === "tool_running";
    pausedForJarvisRef.current = busy;

    if (busy && recRef.current) {
      try {
        recRef.current.stop();
      } catch {
        /* noop */
      }
    } else if (!busy && wantListenRef.current) {
      clearRestart();
      restartTimerRef.current = setTimeout(() => {
        restartTimerRef.current = null;
        if (wantListenRef.current && !pausedForJarvisRef.current && speechSupported) {
          attachRecognition();
        }
      }, 480);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.phase, speechSupported]);

  useEffect(() => {
    if (session.micKillCount === 0) return;
    stopListening();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.micKillCount]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    void session.sendText(text.trim());
    setText("");
  }

  const hasFinder =
    session.finderProgress.length > 0 ||
    !!session.finderMatches ||
    session.finderOpenLog.length > 0;

  const probe = session.macosProbe;
  const macosNeedsAttention =
    !!probe &&
    (probe.in_docker === true ||
      probe.native_macos_backend === false ||
      probe.permissions_complete === false ||
      (probe.warnings?.length ?? 0) > 0 ||
      probe.file_actions_native === false);
  const showMacosPanel =
    !!probe && (probe.platform === "Darwin" || probe.in_docker === true);

  const phaseActive = session.phase !== "idle";

  const rootClass =
    placement === "corner"
      ? "pointer-events-auto relative z-50 flex max-w-[min(92vw,320px)] flex-col items-end pb-1 pt-1"
      : "pointer-events-auto fixed bottom-6 right-5 z-50 flex max-w-[min(92vw,320px)] flex-col items-end pb-[max(1rem,env(safe-area-inset-bottom))] pt-2 sm:bottom-8 sm:right-8";

  return (
    <div className={rootClass}>
      <AnimatePresence>
        {micBusy && micHint ? (
          <motion.p
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          className="mb-1.5 max-w-full truncate text-right font-mono text-[8px] tracking-wide text-white/[0.35]"
          >
            {micHint}
          </motion.p>
        ) : null}
      </AnimatePresence>

      {session.finderMatches?.matches.length ? (
        <div className="mb-2 flex max-w-full justify-end gap-1 overflow-x-auto border-b border-white/[0.06] pb-2 [scrollbar-width:thin]">
          {session.finderMatches.matches.slice(0, 12).map((row) => (
            <button
              key={`${row.index}-${row.path}`}
              type="button"
              onClick={() => void session.sendText(`open number ${row.index}`)}
              className="shrink-0 border border-white/15 bg-black/50 px-2 py-1 font-mono text-[8px] uppercase tracking-wider text-white/70 transition hover:border-cyan-400/35 hover:bg-cyan-500/10 hover:text-cyan-100"
            >
              #{row.index} {row.name.slice(0, 20)}
              {row.name.length > 20 ? "…" : ""}
            </button>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-end gap-1 border border-white/[0.1] bg-black/45 px-2 py-1.5 backdrop-blur-md">
        <div
          className="flex items-center gap-2 px-2 py-1"
          title={session.connected ? "Connected" : "Offline"}
        >
          <span
            className={`relative h-1.5 w-1.5 rounded-full ${
              session.connected ? "bg-emerald-400" : "bg-rose-500"
            }`}
          />
          <span
            className={`font-orbitron text-[8px] font-medium uppercase tracking-[0.22em] ${
              phaseActive ? "text-cyan-200/90" : "text-white/[0.35]"
            }`}
          >
            {phaseLabel}
          </span>
        </div>

        <span className="hidden h-4 w-px bg-white/10 sm:block" aria-hidden />

        {micBusy ? (
          <button
            type="button"
            onClick={stopListening}
            className="border border-rose-400/35 bg-rose-500/10 px-3 py-2 font-orbitron text-[8px] font-medium uppercase tracking-[0.2em] text-rose-100/95 transition hover:bg-rose-500/20"
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            disabled={!session.connected}
            onClick={startListening}
            className="group relative flex h-10 w-10 items-center justify-center border border-cyan-400/35 bg-black/40 disabled:opacity-35"
          >
            {session.phase === "listening" ? (
              <span className="absolute inset-[-4px] border border-cyan-400/25 opacity-50 animate-ping [animation-duration:1.9s]" />
            ) : null}
            <span className="font-orbitron text-[8px] font-semibold uppercase tracking-[0.16em] text-cyan-100">
              MIC
            </span>
          </button>
        )}

        <button
          type="button"
          onClick={() => setShowType((v) => !v)}
          className="border border-transparent px-2 py-2 font-orbitron text-[8px] uppercase tracking-[0.22em] text-zinc-500 transition hover:border-cyan-400/20 hover:text-cyan-200/90"
        >
          Type
        </button>

        <button
          type="button"
          onClick={() => setShowSystem((v) => !v)}
          className={`border border-transparent px-2 py-2 font-orbitron text-[8px] uppercase tracking-[0.22em] transition hover:border-cyan-400/20 ${
            macosNeedsAttention ? "text-amber-200/90" : "text-zinc-600 hover:text-zinc-400"
          }`}
          title="System"
        >
          ···
        </button>
      </div>

      {showType ? (
        <form
          onSubmit={onSubmit}
          className="glass-holo mt-3 w-full max-w-md p-3"
        >
          <textarea
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Message…"
            className="w-full resize-none rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-cyan-400/40"
          />
          <div className="mt-2 flex gap-2">
            <button
              type="submit"
              className="flex-1 rounded-xl border border-cyan-400/40 bg-cyan-500/15 py-2 text-xs font-medium text-cyan-100"
            >
              Send
            </button>
            <button
              type="button"
              onClick={session.flushBuffers}
              className="rounded-xl border border-zinc-700 px-3 py-2 text-xs text-zinc-400"
            >
              Clear
            </button>
          </div>
        </form>
      ) : null}

      {showSystem ? (
        <div className="glass-holo mt-3 max-h-[min(52vh,420px)] w-full max-w-md overflow-y-auto p-4 text-left">
          <p className="text-[10px] font-medium uppercase tracking-[0.25em] text-cyan-400/80">
            Session
          </p>
          <p className="mt-1 break-all font-mono text-[10px] text-zinc-500">
            {session.backendHealth ?? "—"} · {session.sessionId?.slice(0, 10) ?? "…"}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {modes.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => session.setWakeMode(m.id)}
                className={`rounded-full px-2.5 py-1 text-[10px] ${
                  session.wakeMode === m.id
                    ? "bg-cyan-400/20 text-cyan-100 ring-1 ring-cyan-400/40"
                    : "bg-black/30 text-zinc-500"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>

          {hasFinder ? (
            <details className="mt-4 border-t border-white/10 pt-3">
              <summary className="cursor-pointer text-[10px] text-zinc-500">Finder</summary>
              <div className="mt-2 max-h-36 space-y-1 overflow-y-auto font-mono text-[10px] text-zinc-500">
                {session.finderProgress.map((ln) => (
                  <p key={ln.id}>{ln.message}</p>
                ))}
              </div>
            </details>
          ) : null}

          {showMacosPanel ? (
            <details className="mt-3 border-t border-white/10 pt-3" open={macosNeedsAttention}>
              <summary className="cursor-pointer text-[10px] text-zinc-500">macOS permissions</summary>
              <div className="mt-2">
                <MacosHostPanel probe={probe} />
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
