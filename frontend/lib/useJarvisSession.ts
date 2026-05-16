"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type OrbPhase =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "tool_running";

type WakeMode = "push_to_talk" | "wake_word" | "always_on";

export type MacosProbe = {
  platform?: string;
  in_docker?: boolean;
  native_macos_backend?: boolean;
  file_actions_native?: boolean;
  home?: string | null;
  host_python_executable?: string;
  permission_checks?: Array<{
    id?: string;
    label?: string;
    status?: string;
    detail?: string;
  }>;
  permissions_complete?: boolean;
  setup_sections?: Array<{
    id: string;
    title: string;
    steps: string[];
    after_save?: string;
  }>;
  relaunch_hint?: string;
  warnings?: string[];
  setup?: string[];
  permissions?: Record<string, unknown>;
};

type TraceLine = {
  id: string;
  stage: string;
  summary: string;
  name?: string;
};

type TranscriptLine = { id: string; role: "you" | "jarvis" | "system"; text: string };
type ToolLine = { id: string; kind: string; summary: string };

export type FinderMatchRow = {
  index: number;
  name: string;
  path: string;
  file_type: string;
  modified: string;
  is_directory: boolean;
};

type FinderProgressLine = {
  id: string;
  message: string;
  phase?: string;
  matchCount?: number;
  directory?: string;
};

export type FilesystemActivityLine = {
  id: string;
  phase: string;
  message: string;
  path?: string;
};

export type JarvisSession = ReturnType<typeof useJarvisSession>;

export function useJarvisSession() {
  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<AudioContext | null>(null);
  const wakeModeRef = useRef<WakeMode>("push_to_talk");
  const lastReplyRef = useRef<string>("");
  const ttsFallbackRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [connected, setConnected] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [phase, setPhase] = useState<OrbPhase>("idle");
  const [wakeMode, setWakeModeState] = useState<WakeMode>("push_to_talk");
  const [transcriptLines, setTranscriptLines] = useState<TranscriptLine[]>([]);
  const [toolLog, setToolLog] = useState<ToolLine[]>([]);
  const [backendHealth, setBackendHealth] = useState<string | null>(null);
  const [lastAudioLabel, setLastAudioLabel] = useState("idle");
  const [micKillCount, setMicKillCount] = useState(0);
  const [thinkingHint, setThinkingHint] = useState<string | null>(null);
  const [finderProgress, setFinderProgress] = useState<FinderProgressLine[]>([]);
  const [finderMatches, setFinderMatches] = useState<{
    keyword: string;
    matches: FinderMatchRow[];
  } | null>(null);
  const [finderOpenLog, setFinderOpenLog] = useState<{ id: string; message: string }[]>([]);
  const [fsActivity, setFsActivity] = useState<FilesystemActivityLine[]>([]);
  const [macosProbe, setMacosProbe] = useState<MacosProbe | null>(null);
  const [traceLog, setTraceLog] = useState<TraceLine[]>([]);

  const apiBase = useMemo(
    () => process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000",
    [],
  );
  const wsUrl = useMemo(() => {
    const fromEnv = process.env.NEXT_PUBLIC_WS_URL;
    if (fromEnv) return fromEnv;
    const u = new URL(apiBase);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/ws/session";
    u.search = "";
    return u.toString();
  }, [apiBase]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const warm = () => window.speechSynthesis.getVoices();
    warm();
    window.speechSynthesis.addEventListener("voiceschanged", warm);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", warm);
  }, []);

  const speakBrowserFallback = useCallback((text: string) => {
    const raw = text.trim();
    if (!raw || typeof window === "undefined" || !window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(raw.slice(0, 4000));
      u.lang = "en-GB";
      u.rate = 0.97;
      u.pitch = 1;
      const voices = window.speechSynthesis.getVoices();
      const pick =
        voices.find((x) => x.lang.startsWith("en-GB") && /Daniel|Arthur|Sophie/i.test(x.name)) ??
        voices.find((x) => x.lang.startsWith("en-GB")) ??
        voices.find((x) => x.lang.startsWith("en"));
      if (pick) u.voice = pick;
      window.speechSynthesis.speak(u);
      setLastAudioLabel("Browser voice (fallback)");
    } catch {
      setLastAudioLabel("TTS failed");
    }
  }, []);

  useEffect(() => {
    wakeModeRef.current = wakeMode;
  }, [wakeMode]);

  const appendLine = useCallback((line: Omit<TranscriptLine, "id">) => {
    setTranscriptLines((prev) => [
      ...prev,
      { ...line, id: crypto.randomUUID() },
    ]);
  }, []);

  const pushTool = useCallback((kind: string, summary: string) => {
    setToolLog((prev) => [
      ...prev.slice(-12),
      { id: crypto.randomUUID(), kind, summary },
    ]);
  }, []);

  const unlockAudio = useCallback(async () => {
    try {
      if (!audioRef.current) {
        audioRef.current = new AudioContext({ latencyHint: "interactive" });
      }
      if (audioRef.current.state === "suspended") {
        await audioRef.current.resume();
      }
    } catch {
      /* Safari / privacy mode */
    }
  }, []);

  const playBase64Wav = useCallback(
    async (b64: string, fallbackText?: string) => {
      try {
        await unlockAudio();
        if (!audioRef.current) {
          audioRef.current = new AudioContext({ latencyHint: "interactive" });
        }
        const ctx = audioRef.current;
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        if (bytes.length < 64) {
          throw new Error("empty audio");
        }
        const buffer = await ctx.decodeAudioData(bytes.buffer.slice(0));
        const src = ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(ctx.destination);
        src.start();
        setLastAudioLabel(`${buffer.duration.toFixed(2)}s clip`);
      } catch {
        setLastAudioLabel("WAV decode failed — using browser voice");
        if (fallbackText?.trim()) {
          speakBrowserFallback(fallbackText.trim());
        }
      }
    },
    [unlockAudio, speakBrowserFallback],
  );

  useEffect(() => {
    let cancelled = false;
    async function ping() {
      try {
        const res = await fetch(`${apiBase}/health`);
        if (!res.ok) throw new Error("bad health");
        const body = await res.json();
        if (!cancelled) setBackendHealth(`${body.model ?? "ollama"}`);
      } catch {
        if (!cancelled) setBackendHealth("offline");
      }
    }
    async function macosDiag() {
      try {
        const res = await fetch(`${apiBase}/health/macos`);
        if (!res.ok) return;
        const body = (await res.json()) as MacosProbe;
        if (!cancelled && body && typeof body === "object") {
          setMacosProbe(body);
        }
      } catch {
        /* API down or old build */
      }
    }
    ping();
    void macosDiag();
    const healthId = setInterval(ping, 15000);
    const macosId = setInterval(() => void macosDiag(), 30000);
    return () => {
      cancelled = true;
      clearInterval(healthId);
      clearInterval(macosId);
    };
  }, [apiBase]);

  useEffect(() => {
    let manualClose = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (manualClose) return;

      const sock = new WebSocket(wsUrl);

      // Only this instance is allowed to drive wsRef / connected until it is replaced.
      wsRef.current = sock;

      sock.onopen = () => {
        if (wsRef.current !== sock) return;
        void unlockAudio();
        setConnected(true);
        appendLine({ role: "system", text: "Secure channel opened." });
        try {
          sock.send(
            JSON.stringify({
              type: "config",
              payload: { wake_mode: wakeModeRef.current },
            }),
          );
        } catch {
          appendLine({ role: "system", text: "Could not send config frame." });
        }
      };

      sock.onerror = () => {
        // onerror often precedes onclose; avoid duplicate scary lines if we're not the active sock
        if (wsRef.current !== sock) return;
        appendLine({
          role: "system",
          text: "WebSocket error — check that the API is on :8000 (uvicorn running).",
        });
      };

      sock.onclose = () => {
        // Critical: an OLD socket must not clear wsRef if a NEWER socket already replaced it
        // (React Strict Mode remount, or reconnect overlap).
        if (wsRef.current !== sock) {
          return;
        }
        wsRef.current = null;
        setConnected(false);
        if (manualClose) {
          return;
        }
        appendLine({
          role: "system",
          text: "Channel closed — retrying in 2.5s…",
        });
        retryTimer = setTimeout(connect, 2500);
      };

      sock.onmessage = async (event) => {
        if (wsRef.current !== sock) return;
        let msg: { type: string; payload: Record<string, unknown> };
        try {
          msg = JSON.parse(event.data as string) as {
            type: string;
            payload: Record<string, unknown>;
          };
        } catch {
          appendLine({ role: "system", text: "Bad packet from server." });
          return;
        }
        switch (msg.type) {
          case "jarvis_trace": {
            const stage = String(msg.payload.stage ?? "");
            const summary = String(msg.payload.summary ?? "");
            const name =
              typeof msg.payload.name === "string" ? msg.payload.name : undefined;
            setTraceLog((prev) => [
              ...prev.slice(-48),
              { id: crypto.randomUUID(), stage, summary, name },
            ]);
            if (summary) {
              pushTool(`trace:${stage}`, summary);
            }
            break;
          }
          case "session":
            setSessionId(String(msg.payload.session_id ?? ""));
            if (msg.payload.macos && typeof msg.payload.macos === "object") {
              setMacosProbe(msg.payload.macos as MacosProbe);
            }
            break;
          case "pong":
            break;
          case "state":
            setPhase((msg.payload.phase as OrbPhase) ?? "idle");
            break;
          case "thinking_hint": {
            const hint = String(msg.payload.text ?? "").trim();
            if (hint) {
              setThinkingHint(hint);
              appendLine({ role: "system", text: hint });
            }
            break;
          }
          case "transcript":
            appendLine({ role: "you", text: String(msg.payload.text ?? "") });
            break;
          case "assistant_delta":
            break;
          case "assistant_final": {
            setThinkingHint(null);
            const line = String(msg.payload.text ?? "");
            lastReplyRef.current = line;
            appendLine({ role: "jarvis", text: line });
            const browserTts = msg.payload.browser_tts === true;
            if (ttsFallbackRef.current) {
              clearTimeout(ttsFallbackRef.current);
              ttsFallbackRef.current = null;
            }
            if (browserTts) {
              speakBrowserFallback(line);
            } else {
              ttsFallbackRef.current = setTimeout(() => {
                speakBrowserFallback(line);
                ttsFallbackRef.current = null;
              }, 2400);
            }
            break;
          }
          case "speech_audio": {
            if (ttsFallbackRef.current) {
              clearTimeout(ttsFallbackRef.current);
              ttsFallbackRef.current = null;
            }
            if (typeof window !== "undefined" && window.speechSynthesis) {
              window.speechSynthesis.cancel();
            }
            if (msg.payload.base64) {
              await playBase64Wav(
                String(msg.payload.base64),
                lastReplyRef.current,
              );
            } else {
              speakBrowserFallback(lastReplyRef.current);
            }
            break;
          }
          case "mic_control": {
            if (msg.payload.listen === false) {
              setMicKillCount((c) => c + 1);
              appendLine({
                role: "system",
                text: "Listening paused — tap Speak when you need me again.",
              });
            }
            break;
          }
          case "tool_event": {
            const nm = String(msg.payload.name ?? "tool");
            const sm =
              typeof msg.payload.summary === "string" && msg.payload.summary.trim()
                ? msg.payload.summary.trim()
                : JSON.stringify(msg.payload.args ?? {});
            pushTool(nm, sm);
            break;
          }
          case "finder_search_progress": {
            const phase = String(msg.payload.phase ?? "");
            if (phase === "start") {
              setFinderProgress([]);
              setFinderOpenLog([]);
            }
            const line: FinderProgressLine = {
              id: crypto.randomUUID(),
              message: String(msg.payload.message ?? ""),
              phase: phase || undefined,
              matchCount:
                typeof msg.payload.match_count === "number"
                  ? msg.payload.match_count
                  : undefined,
              directory:
                typeof msg.payload.directory === "string"
                  ? msg.payload.directory
                  : undefined,
            };
            setFinderProgress((prev) => [...prev.slice(-48), line]);
            pushTool("mac_finder", line.message);
            break;
          }
          case "finder_match_list": {
            const keyword = String(msg.payload.keyword ?? "");
            const raw = msg.payload.matches;
            const matches: FinderMatchRow[] = Array.isArray(raw)
              ? (raw as Record<string, unknown>[]).map((o) => ({
                  index: Number(o.index) || 0,
                  name: String(o.name ?? ""),
                  path: String(o.path ?? ""),
                  file_type: String(o.file_type ?? ""),
                  modified: String(o.modified ?? ""),
                  is_directory: Boolean(o.is_directory),
                }))
              : [];
            setFinderMatches({ keyword, matches });
            break;
          }
          case "finder_open_status": {
            const path = String(msg.payload.path ?? "");
            const status = String(msg.payload.status ?? "");
            const message = String(msg.payload.message ?? "");
            const text = `${status}: ${message}${path ? ` — ${path.split("/").pop() ?? path}` : ""}`;
            setFinderOpenLog((prev) => [
              ...prev.slice(-24),
              { id: crypto.randomUUID(), message: text },
            ]);
            pushTool("mac_finder_open", text);
            break;
          }
          case "filesystem_activity": {
            const phase = String(msg.payload.phase ?? "");
            if (phase === "start") {
              setFsActivity([]);
            }
            const row: FilesystemActivityLine = {
              id: crypto.randomUUID(),
              phase,
              message: String(msg.payload.message ?? ""),
              path: typeof msg.payload.path === "string" ? msg.payload.path : undefined,
            };
            setFsActivity((prev) => [...prev.slice(-24), row]);
            const tail = row.path ? ` · ${row.path.split("/").pop() ?? row.path}` : "";
            pushTool("filesystem", `${row.phase}: ${row.message}${tail}`);
            break;
          }
          case "local_file_action": {
            const raw =
              typeof process !== "undefined"
                ? process.env.NEXT_PUBLIC_FILE_BRIDGE_URL?.trim()
                : "";
            const base = (raw || "http://127.0.0.1:17834").replace(/\/$/, "");
            const path = String(msg.payload.path ?? "");
            const action = String(msg.payload.action ?? "reveal");
            if (!path) break;
            const suffix = action === "open" ? "/open" : "/reveal";
            void fetch(`${base}${suffix}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path }),
            })
              .then(async (r) => {
                if (!r.ok) {
                  appendLine({
                    role: "system",
                    text: `Desktop bridge HTTP ${r.status} — run: python3 scripts/jarvis_file_bridge.py`,
                  });
                }
              })
              .catch(() => {
                appendLine({
                  role: "system",
                  text: "Desktop bridge unreachable (127.0.0.1:17834). On your Mac run: python3 scripts/jarvis_file_bridge.py — same JARVIS_ALLOWED_ROOTS as the API if you set them.",
                });
              });
            break;
          }
          case "error":
            setThinkingHint(null);
            appendLine({
              role: "system",
              text: `Error: ${String(msg.payload.detail ?? "")}`,
            });
            break;
          default:
            break;
        }
      };
    };

    connect();

    return () => {
      manualClose = true;
      if (ttsFallbackRef.current) {
        clearTimeout(ttsFallbackRef.current);
        ttsFallbackRef.current = null;
      }
      if (retryTimer) clearTimeout(retryTimer);
      setConnected(false);
      const closing = wsRef.current;
      if (closing) {
        wsRef.current = null;
        closing.close();
      }
    };
  }, [wsUrl, appendLine, playBase64Wav, pushTool, speakBrowserFallback, unlockAudio]);

  const sendText = useCallback(
    async (text: string) => {
      await unlockAudio();
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        appendLine({
          role: "system",
          text: "Socket not ready yet — wait for “Secure channel opened” or refresh once uvicorn is up.",
        });
        return;
      }
      ws.send(JSON.stringify({ type: "user_text", payload: { text } }));
    },
    [appendLine, unlockAudio],
  );

  useEffect(() => {
    if (!connected) return;
    const params = new URLSearchParams(window.location.search);
    const vq = params.get("vq");
    if (!vq?.trim()) return;
    void sendText(vq.trim());
    params.delete("vq");
    const qs = params.toString();
    window.history.replaceState(
      {},
      "",
      `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`,
    );
  }, [connected, sendText]);

  const flushBuffers = useCallback(() => {
    setTranscriptLines([]);
    setToolLog([]);
    setThinkingHint(null);
    setFinderProgress([]);
    setFinderMatches(null);
    setFinderOpenLog([]);
    setFsActivity([]);
    setTraceLog([]);
  }, []);

  const setWakeMode = useCallback((mode: WakeMode) => {
    setWakeModeState(mode);
    wakeModeRef.current = mode;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "config", payload: { wake_mode: mode } }));
    }
  }, []);

  return {
    connected,
    sessionId,
    phase,
    wakeMode,
    transcriptLines,
    toolLog,
    backendHealth,
    lastAudioLabel,
    sendText,
    unlockAudio,
    flushBuffers,
    setWakeMode,
    micKillCount,
    thinkingHint,
    finderProgress,
    finderMatches,
    finderOpenLog,
    fsActivity,
    macosProbe,
    traceLog,
  };
}
