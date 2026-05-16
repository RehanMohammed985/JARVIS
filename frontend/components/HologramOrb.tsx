"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import { useMemo, useRef } from "react";
import type { Group, Mesh } from "three";
import * as THREE from "three";
import { motion } from "framer-motion";

import type { OrbPhase } from "@/lib/useJarvisSession";

const CORE = "#00b8d4";
const ACCENT = "#00e5ff";
const DIM = "#66f0ff";
const DEEP = "#007a8c";

const PARTICLE_COUNT = 4200;
const HALO_COUNT = 900;

function useLatest<T>(value: T) {
  const r = useRef(value);
  r.current = value;
  return r;
}

function circlePoints(radius: number, segments: number, z = 0): THREE.Vector3[] {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, z));
  }
  return pts;
}

function HologramCore({
  phase,
  speaking,
}: {
  phase: OrbPhase;
  speaking: boolean;
}) {
  const mesh = useRef<Mesh>(null);
  const phaseRef = useLatest(phase);
  const speakingRef = useLatest(speaking);

  useFrame((state) => {
    const m = mesh.current;
    if (!m) return;
    const t = state.clock.elapsedTime;
    const sp = speakingRef.current;
    const ph = phaseRef.current;
    const wobble =
      ph === "speaking" || sp
        ? Math.sin(t * 16.5) * 0.055 + Math.sin(t * 7.8) * 0.028
        : Math.sin(t * 1.6) * 0.014;
    const breath =
      ph === "listening"
        ? Math.sin(t * 5.2) * 0.018
        : ph === "thinking"
          ? Math.sin(t * 6.8) * 0.022
          : 0;
    const ripple = Math.sin(t * 2.9) * 0.018 + Math.sin(t * 4.4 + 1.1) * 0.01;
    m.scale.setScalar(0.46 + wobble + breath + ripple);
    m.rotation.y = t * 0.18;
    m.rotation.x = Math.sin(t * 0.35) * 0.06;
    const mat = m.material as THREE.MeshBasicMaterial;
    mat.opacity =
      sp || ph === "speaking" ? 0.22 + Math.sin(t * 14) * 0.045 : 0.12;
  });

  return (
    <mesh ref={mesh}>
      <sphereGeometry args={[0.46, 64, 64]} />
      <meshBasicMaterial
        color={CORE}
        transparent
        opacity={0.14}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
}

function SpeakingWaveRings({ speaking, phase }: { speaking: boolean; phase: OrbPhase }) {
  const gRef = useRef<Group>(null);
  const speakingRef = useLatest(speaking);
  const phaseRef = useLatest(phase);

  useFrame((state) => {
    const g = gRef.current;
    if (!g) return;
    const t = state.clock.elapsedTime;
    const sp = speakingRef.current;
    const ph = phaseRef.current;
    const live = sp || ph === "speaking" || ph === "listening";
    const speed = live ? 9.2 : 2.4;
    g.children.forEach((child, i) => {
      const childMesh = child as Mesh;
      const phaseOff = t * speed + i * 1.15;
      const amp = live ? 0.11 + i * 0.024 : 0.04 + i * 0.012;
      const s = 0.55 + i * 0.11 + Math.sin(phaseOff) * amp;
      childMesh.scale.setScalar(s);
      const mat = childMesh.material as THREE.MeshBasicMaterial;
      mat.opacity = live ? 0.055 + i * 0.02 : 0.02 + i * 0.009;
    });
    g.rotation.z = t * (live ? 0.42 : 0.12);
  });

  return (
    <group ref={gRef} rotation={[Math.PI / 2, 0, 0]}>
      {[0, 1, 2, 3, 4].map((i) => (
        <mesh key={i}>
          <torusGeometry args={[0.62 + i * 0.045, 0.008 + i * 0.0015, 8, 128]} />
          <meshBasicMaterial
            color={i % 2 === 0 ? ACCENT : DIM}
            transparent
            opacity={0.05}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      ))}
    </group>
  );
}

function PulseWaves({ phase }: { phase: OrbPhase }) {
  const gRef = useRef<Group>(null);
  const phaseRef = useLatest(phase);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const g = gRef.current;
    if (!g) return;
    const ph = phaseRef.current;
    const live =
      ph === "listening" || ph === "thinking" || ph === "speaking" || ph === "tool_running";
    g.children.forEach((child, i) => {
      const m = child as Mesh;
      const mat = m.material as THREE.MeshBasicMaterial;
      const base = 0.92 + i * 0.085;
      const b = live ? 0.055 : 0.028;
      const wave = Math.sin(t * (2.1 + i * 0.28) + i * 1.4) * b;
      m.scale.setScalar(base + wave);
      mat.opacity = live ? 0.045 + i * 0.014 : 0.022 + i * 0.01;
    });
  });

  return (
    <group ref={gRef}>
      {[0, 1, 2, 3].map((i) => (
        <mesh key={i} rotation={[Math.PI / 2, 0, i * 0.11]}>
          <torusGeometry args={[0.78 + i * 0.07, 0.016, 10, 160]} />
          <meshBasicMaterial
            color={i % 2 === 0 ? ACCENT : DIM}
            transparent
            opacity={0.06}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      ))}
    </group>
  );
}

function HaloDust({ phase, speaking }: { phase: OrbPhase; speaking: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const phaseRef = useLatest(phase);
  const speakingRef = useLatest(speaking);
  const base = useMemo(() => {
    const positions = new Float32Array(HALO_COUNT * 3);
    for (let i = 0; i < HALO_COUNT; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = 2 * Math.PI * u;
      const phi = Math.acos(2 * v - 1);
      const r = 0.82 + Math.random() * 0.52;
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
    }
    return positions;
  }, []);
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(base), 3));
    return g;
  }, [base]);

  useFrame((state) => {
    const pts = ref.current;
    if (!pts) return;
    const t = state.clock.elapsedTime;
    const attr = pts.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const sp = speakingRef.current;
    const ph = phaseRef.current;
    const amp = sp || ph === "speaking" ? 0.035 : 0.014;
    for (let i = 0; i < HALO_COUNT; i++) {
      const ix = i * 3;
      arr[ix] = base[ix] + Math.sin(t * 0.8 + i * 0.11) * amp;
      arr[ix + 1] = base[ix + 1] + Math.cos(t * 0.65 + i * 0.09) * amp;
      arr[ix + 2] = base[ix + 2] + Math.sin(t * 0.55 + i * 0.07) * amp * 0.8;
    }
    attr.needsUpdate = true;
    pts.rotation.y = t * 0.032;
  });

  return (
    <points ref={ref} geometry={geometry}>
      <pointsMaterial
        color="#66f0ff"
        size={0.009}
        transparent
        opacity={0.33}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        sizeAttenuation
      />
    </points>
  );
}

function ParticleNoise({ phase, speaking }: { phase: OrbPhase; speaking: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const phaseRef = useLatest(phase);
  const speakingRef = useLatest(speaking);
  const base = useMemo(() => {
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = 2 * Math.PI * u;
      const phi = Math.acos(2 * v - 1);
      const r = 0.2 + Math.random() * 0.36;
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
    }
    return positions;
  }, []);
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(base), 3));
    return g;
  }, [base]);

  useFrame((state) => {
    const pts = ref.current;
    if (!pts) return;
    const t = state.clock.elapsedTime;
    const attr = pts.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const ph = phaseRef.current;
    const sp = speakingRef.current;
    const amp =
      ph === "thinking"
        ? 0.048
        : ph === "listening"
          ? 0.042
          : ph === "speaking" || sp
            ? 0.058
            : ph === "tool_running"
              ? 0.038
              : 0.022;
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const ix = i * 3;
      const n = Math.sin(t * 1.5 + i * 0.065) * Math.cos(t * 0.95 + i * 0.1);
      arr[ix] = base[ix] + n * amp;
      arr[ix + 1] = base[ix + 1] + Math.cos(t * 1.05 + i * 0.085) * amp * 0.88;
      arr[ix + 2] = base[ix + 2] + Math.sin(t * 0.88 + i * 0.048) * amp * 0.72;
    }
    attr.needsUpdate = true;
    pts.rotation.y = t * 0.072;
    pts.rotation.x = Math.sin(t * 0.22) * 0.065;
  });

  return (
    <points ref={ref} geometry={geometry}>
      <pointsMaterial
        color="#00e5ff"
        size={0.01}
        transparent
        opacity={0.48}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        sizeAttenuation
      />
    </points>
  );
}

function TechRings({
  phase,
  speaking,
}: {
  phase: OrbPhase;
  speaking: boolean;
}) {
  const group = useRef<Group>(null);
  const phaseRef = useLatest(phase);
  const speakingRef = useLatest(speaking);
  const p1 = useMemo(() => circlePoints(1.24, 128, 0), []);
  const p2 = useMemo(() => circlePoints(1.04, 80, 0), []);
  const p3 = useMemo(() => circlePoints(1.48, 64, 0), []);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const g = group.current;
    if (!g) return;
    const ph = phaseRef.current;
    const sp = speakingRef.current;
    const s =
      ph === "thinking" ? 1.09 : ph === "listening" ? 1.062 : sp ? 1.07 : 1;
    const pulse =
      ph === "listening"
        ? Math.sin(t * 4.5) * 0.02
        : ph === "thinking"
          ? Math.sin(t * 5.8) * 0.025
          : sp
            ? Math.sin(t * 6.2) * 0.017
            : Math.sin(t * 1.7) * 0.009;
    g.scale.setScalar(s + pulse);
    g.children.forEach((child, i) => {
      child.rotation.z = t * (0.28 + i * 0.11) * (i % 2 === 0 ? 1 : -1);
    });
  });

  return (
    <group ref={group} rotation={[Math.PI / 2, 0, 0]}>
      <Line
        points={p1}
        color={ACCENT}
        lineWidth={1.85}
        transparent
        opacity={0.38}
        dashed
        dashScale={2}
        dashSize={0.062}
        gapSize={0.036}
      />
      <Line
        points={p2}
        color={DIM}
        lineWidth={1.2}
        transparent
        opacity={0.24}
        dashed
        dashScale={2}
        dashSize={0.05}
        gapSize={0.045}
      />
      <Line
        points={p3}
        color={DEEP}
        lineWidth={0.9}
        transparent
        opacity={0.16}
        dashed
        dashScale={2}
        dashSize={0.1}
        gapSize={0.072}
      />
    </group>
  );
}

function WireCore({ phase }: { phase: OrbPhase }) {
  const outer = useRef<Mesh>(null);
  const inner = useRef<Mesh>(null);
  const phaseRef = useLatest(phase);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const ph = phaseRef.current;
    const boost =
      ph === "thinking" ? 1.48 : ph === "listening" ? 1.24 : ph === "speaking" ? 1.32 : 1;
    const ripple =
      Math.sin(t * 3.15) * 0.034 + Math.sin(t * 5.1 + 0.9) * 0.019;
    if (outer.current) {
      outer.current.rotation.set(t * 0.52, t * 0.76, t * 0.3);
      outer.current.scale.setScalar(0.52 + boost * 0.024 + ripple);
    }
    if (inner.current) {
      inner.current.rotation.set(-t * 0.62, t * 0.42, t * 0.36);
    }
  });

  return (
    <group>
      <mesh ref={outer}>
        <icosahedronGeometry args={[0.5, 2]} />
        <meshBasicMaterial color={ACCENT} wireframe transparent opacity={0.58} />
      </mesh>
      <mesh ref={inner}>
        <icosahedronGeometry args={[0.3, 1]} />
        <meshBasicMaterial color={DIM} wireframe transparent opacity={0.42} />
      </mesh>
    </group>
  );
}

function ScanSweep({ active }: { active: boolean }) {
  const mesh = useRef<Mesh>(null);
  const activeRef = useLatest(active);

  useFrame((state) => {
    const m = mesh.current;
    if (!m) return;
    const t = state.clock.elapsedTime;
    const isOn = activeRef.current;
    m.rotation.z = t * (isOn ? 1.8 : 0.55);
    m.scale.setScalar(0.009 + (isOn ? 0.004 : 0) * Math.sin(t * 3.8));
    const mat = m.material as THREE.MeshBasicMaterial;
    mat.opacity = isOn ? 0.014 : 0.008;
  });
  return (
    <mesh ref={mesh} rotation={[0, 0, 0]} position={[0, 0, 0.01]}>
      <planeGeometry args={[2.55, 2.55]} />
      <meshBasicMaterial
        color="#ccfaff"
        transparent
        opacity={active ? 0.014 : 0.008}
        side={THREE.DoubleSide}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
}

function Scene({ phase, speaking }: { phase: OrbPhase; speaking: boolean }) {
  const active = phase !== "idle";
  return (
    <>
      <ambientLight intensity={0.2} />
      <HologramCore phase={phase} speaking={speaking} />
      <WireCore phase={phase} />
      <ParticleNoise phase={phase} speaking={speaking} />
      <HaloDust phase={phase} speaking={speaking} />
      <SpeakingWaveRings speaking={speaking} phase={phase} />
      <PulseWaves phase={phase} />
      <TechRings phase={phase} speaking={speaking} />
      <ScanSweep active={active} />
    </>
  );
}

export function HologramOrb({
  phase,
  speaking,
}: {
  phase: OrbPhase;
  speaking: boolean;
}) {
  return (
    <motion.div
      className="relative mx-auto max-w-full bg-transparent"
      style={{
        width: `min(80vw, min(54vh, 640px))`,
        aspectRatio: "1",
      }}
      animate={{
        scale:
          phase === "listening"
            ? 1.028
            : phase === "thinking"
              ? 1.018
              : phase === "speaking"
                ? 1.034
                : 1,
      }}
      transition={{ type: "spring", stiffness: 120, damping: 22 }}
    >
      {/* Diffuse wash only — no hard disc, no “screen” frame (matches free-floating ref) */}
      <div
        className="pointer-events-none absolute left-1/2 top-[42%] z-0 h-[min(140%,780px)] w-[min(140%,780px)] -translate-x-1/2 -translate-y-1/2 opacity-70 blur-[110px]"
        style={{
          background:
            "radial-gradient(circle at 50% 45%, rgba(0, 229, 255, 0.11) 0%, rgba(0, 229, 255, 0.03) 42%, transparent 72%)",
        }}
        aria-hidden
      />
      <div
        className="pointer-events-none relative z-[1] h-full w-full [-webkit-mask-image:radial-gradient(circle_at_50%_42%,#000_50%,transparent_78%)] [mask-image:radial-gradient(circle_at_50%_42%,#000_50%,transparent_78%)]"
      >
        <Canvas
          className="block h-full w-full touch-none !bg-transparent [&_canvas]:block [&_canvas]:!bg-transparent"
          style={{ touchAction: "none", background: "transparent" }}
          camera={{ position: [0, 0, 2.58], fov: 45 }}
          dpr={[1, 2]}
          gl={{
            antialias: true,
            alpha: true,
            premultipliedAlpha: true,
            powerPreference: "high-performance",
          }}
          frameloop="always"
          onCreated={({ gl, scene }) => {
            gl.setClearColor(0x000000, 0);
            scene.background = null;
          }}
        >
          <Scene phase={phase} speaking={speaking} />
        </Canvas>
      </div>
      <div
        className="pointer-events-none absolute left-1/2 top-[42%] z-[4] -translate-x-1/2 -translate-y-1/2"
        aria-hidden
      >
        <span className="select-none font-exo text-[clamp(0.48rem,1.72vw,0.74rem)] font-thin uppercase tracking-[0.78em] text-white [text-shadow:0_0_14px_rgba(255,255,255,0.1)]">
          JARVIS
        </span>
      </div>
    </motion.div>
  );
}
