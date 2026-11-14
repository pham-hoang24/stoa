import { memo, useCallback, useEffect, useRef, useState } from "react"
import { ArrowRight, Pause, Play } from "lucide-react"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import { AREA_UNIT, AREA_VALUE, ROOMS_COUNT, area, rooms, type Evidence } from "@/data/evidence"

type SceneId = "area" | "rooms" | "abstain"

type Scene = {
  id: SceneId
  tab: string
  question: string
  source: string
  lane: string
  value: number | null
  unit: string
  note: string
  evidence: Evidence[]
  /** user-space camera target on the sheet; null keeps the whole building in view */
  focus: { x: number; y: number; s: number } | null
}

const SCENES: Scene[] = [
  {
    id: "area",
    tab: "Room area",
    question: "What is the net floor area of room 2.10 ('Zimmer') in m²?",
    source: "swiss_dwellings · PDF",
    lane: "swiss",
    value: AREA_VALUE,
    unit: AREA_UNIT,
    note: "The area of the room's boundary polygon, read from the DXF next to this PDF. Ten vertices, no model call.",
    evidence: [area],
    focus: { x: 617, y: 302, s: 2.3 },
  },
  {
    id: "rooms",
    tab: "Count rooms",
    question: "How many rooms labelled 'Zimmer' are there on this floor?",
    source: "swiss_dwellings · PDF",
    lane: "swiss",
    value: ROOMS_COUNT,
    unit: "rooms",
    note: "One boundary polygon per labelled room, read from the DXF. Click a room to compare it with the printed label.",
    evidence: rooms,
    focus: null,
  },
  {
    id: "abstain",
    tab: "Missing room",
    question: "What is the net floor area of room 9.99 ('Zimmer') in m²?",
    source: "swiss_dwellings · PDF",
    lane: "swiss",
    value: null,
    unit: "",
    note: "declined: room 9.99 not found on this floor. Nothing is guessed and nothing is passed to a language model.",
    evidence: [],
    focus: null,
  },
]

const SCENE_MS = 10500
const VB = { x: 465, y: 55, w: 265, h: 605 }

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  )
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)")
    const on = () => setReduced(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  return reduced
}

/** 0 question typed, 1 routed, 2 evidence drawn, 3 answer shown, 4 settled */
function useStage(sceneId: SceneId, qLen: number, reduced: boolean) {
  const [stage, setStage] = useState(reduced ? 4 : 0)
  useEffect(() => {
    if (reduced) {
      setStage(4)
      return
    }
    setStage(0)
    const typed = qLen * 22 + 300
    const t = [typed, typed + 600, typed + 2200, typed + 3400].map((ms, i) => window.setTimeout(() => setStage(i + 1), ms))
    return () => t.forEach(window.clearTimeout)
  }, [sceneId, qLen, reduced])
  return stage
}

function Typewriter({ text, run }: { text: string; run: boolean }) {
  const [n, setN] = useState(run ? 0 : text.length)
  useEffect(() => {
    if (!run) {
      setN(text.length)
      return
    }
    setN(0)
    const id = window.setInterval(() => setN((v) => (v >= text.length ? (window.clearInterval(id), v) : v + 1)), 22)
    return () => window.clearInterval(id)
  }, [text, run])
  return (
    <>
      <span aria-hidden>{text.slice(0, n)}</span>
      <span aria-hidden className={cn("ml-px inline-block h-[1.1em] w-px translate-y-[0.2em] bg-foreground", n >= text.length && "opacity-0")} />
      <span className="sr-only">{text}</span>
    </>
  )
}

function CountUp({ to, run, decimals }: { to: number; run: boolean; decimals: number }) {
  const [v, setV] = useState(run ? 0 : to)
  useEffect(() => {
    if (!run) {
      setV(to)
      return
    }
    let raf = 0
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / 900)
      setV(to * (1 - Math.pow(1 - p, 4)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [to, run])
  return <>{v.toFixed(decimals)}</>
}

/** The real sheet never changes between scenes, so it never re-renders. */
const Sheet = memo(function Sheet() {
  return <image href="/sheet.svg" x="0" y="0" width="1190.551" height="841.89" />
})

export function EvidenceDemo() {
  const reduced = usePrefersReducedMotion()
  const [sceneId, setSceneId] = useState<SceneId>("area")
  const [playing, setPlaying] = useState(true)
  const [hover, setHover] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const scene = SCENES.find((s) => s.id === sceneId)!
  const stage = useStage(sceneId, scene.question.length, reduced)
  const autoplay = playing && !reduced
  const active = hover ?? picked

  const go = useCallback((id: SceneId) => {
    setSceneId(id)
    setHover(null)
    setPicked(null)
  }, [])

  // Auto-advance. Stops for good as soon as the visitor touches the demo.
  const idx = SCENES.findIndex((s) => s.id === sceneId)
  const next = useRef(go)
  next.current = go
  useEffect(() => {
    if (!autoplay) return
    const id = window.setTimeout(() => next.current(SCENES[(idx + 1) % SCENES.length].id), SCENE_MS)
    return () => window.clearTimeout(id)
  }, [autoplay, idx, sceneId])

  const choose = (key: string) => {
    setPicked((p) => (p === key ? null : key))
    setPlaying(false)
  }

  const f = scene.focus
  const zoom = f && stage >= 2 ? `translate(${VB.x + VB.w / 2 - f.s * f.x}px, ${VB.y + VB.h / 2 - f.s * f.y}px) scale(${f.s})` : "none"
  const abstain = scene.value === null
  const showEvidence = stage >= 2
  const answered = stage >= 3

  return (
    <figure className="m-0" aria-labelledby="demo-cap">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tabs
          value={sceneId}
          onValueChange={(v) => {
            setPlaying(false)
            go(v as SceneId)
          }}
        >
          <TabsList className="h-auto flex-wrap justify-start gap-1 bg-transparent p-0">
            {SCENES.map((s) => (
              <TabsTrigger
                key={s.id}
                value={s.id}
                className="h-9 flex-none rounded-full border-border px-4 data-active:border-forest-950 data-active:bg-forest-950 data-active:text-primary-foreground"
              >
                {s.tab}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {!reduced && (
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            aria-pressed={!playing}
            className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm outline-none transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            {playing ? "Pause tour" : "Play tour"}
          </button>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border bg-card shadow-[0_0_0_1px_#0000000d,0_1px_2px_#0000000a,0_18px_40px_-24px_#00000026]">
        {autoplay && (
          <div className="h-0.5 bg-mist" aria-hidden>
            <div key={sceneId} className="tour-progress h-full origin-left bg-forest-800" style={{ ["--ms" as string]: `${SCENE_MS}ms` }} />
          </div>
        )}
        <div className="grid sm:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
          <div className="relative overflow-hidden border-b bg-white sm:border-r sm:border-b-0">
            <svg
              viewBox={`${VB.x} ${VB.y} ${VB.w} ${VB.h}`}
              role="group"
              aria-label="Real Swiss Dwellings floor plan with the evidence for the selected question"
              className="block h-[26rem] w-full sm:h-[36rem]"
              preserveAspectRatio="xMidYMid meet"
            >
              <g className="sheet-cam" style={{ transform: zoom, transformOrigin: "0 0" }}>
                <Sheet />
                {abstain && stage >= 1 && <rect key="scan" x={VB.x} y={VB.y} width={VB.w} height="3" fill="var(--abstain)" opacity="0.5" className="scan-line" />}
                {abstain && stage >= 3 && (
                  <rect x={VB.x + 3} y={VB.y + 3} width={VB.w - 6} height={VB.h - 6} fill="none" stroke="var(--abstain)" strokeWidth="1.4" strokeDasharray="6 4" />
                )}
                {showEvidence &&
                  scene.evidence.map((e, i) => {
                    const on = active === e.key
                    const many = scene.evidence.length > 1
                    return (
                      <g
                        key={e.key}
                        role="button"
                        tabIndex={0}
                        aria-pressed={picked === e.key}
                        aria-label={`Evidence ${e.key}: ${e.label}`}
                        className="ev cursor-pointer outline-none"
                        style={{ ["--d" as string]: `${i * 0.09}s` }}
                        onMouseEnter={() => setHover(e.key)}
                        onMouseLeave={() => setHover(null)}
                        onFocus={() => setHover(e.key)}
                        onBlur={() => setHover(null)}
                        onClick={() => choose(e.key)}
                        onKeyDown={(ev) => {
                          if (ev.key === "Enter" || ev.key === " ") {
                            ev.preventDefault()
                            choose(e.key)
                          }
                        }}
                      >
                        <polygon
                          points={e.points}
                          pathLength={1}
                          className="ev-poly"
                          fill="var(--evidence)"
                          fillOpacity={on ? 0.34 : 0.16}
                          stroke="var(--evidence)"
                          strokeWidth={on ? 2.4 : 1.6}
                          strokeLinejoin="round"
                        />
                        {many && (
                          <g className="ev-badge" style={{ ["--d" as string]: `${0.5 + i * 0.09}s` }}>
                            <circle cx={e.bbox[0]} cy={e.bbox[1]} r={8} fill="var(--evidence)" stroke="white" strokeWidth={1.2} />
                            <text x={e.bbox[0]} y={e.bbox[1] + 3.2} textAnchor="middle" fontSize="9" fontWeight="700" fill="white" className="font-mono">
                              {e.key}
                            </text>
                          </g>
                        )}
                        {!many &&
                          e.points.split(" ").map((p, k) => {
                            const [x, y] = p.split(",").map(Number)
                            return <rect key={k} x={x - 1.6} y={y - 1.6} width={3.2} height={3.2} fill="white" stroke="var(--evidence)" strokeWidth={1} className="ev-vertex" style={{ ["--d" as string]: `${0.6 + k * 0.07}s` }} />
                          })}
                      </g>
                    )
                  })}
              </g>
            </svg>
          </div>

          <div className="flex flex-col gap-5 p-5 sm:p-6">
            <div>
              <p className="label mb-2">Question</p>
              <p className="min-h-[3.1em] text-[17px] leading-snug font-medium">
                <Typewriter key={sceneId} text={scene.question} run={!reduced} />
              </p>
            </div>

            <div className={cn("flex flex-wrap items-center gap-2 text-sm transition-all duration-500 ease-out-quart", stage >= 1 ? "opacity-100" : "translate-y-1 opacity-0")}>
              <span className="rounded-md bg-mist px-2 py-1 font-mono text-[12px]">{scene.source}</span>
              <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
              <span className="rounded-md bg-forest-950 px-2 py-1 font-mono text-[12px] text-primary-foreground">lane {scene.lane}</span>
            </div>

            <div
              className={cn(
                "rounded-lg px-4 py-3 transition-all duration-500 ease-out-quart",
                abstain ? "bg-abstain-soft" : "bg-mist",
                answered ? "opacity-100" : "translate-y-1 opacity-0",
              )}
              aria-live="polite"
            >
              <p className="label mb-1">{abstain ? "Abstained" : "Answer"}</p>
              {abstain ? (
                <p className="text-lg font-semibold text-abstain">No value</p>
              ) : (
                <p className="text-3xl font-semibold tracking-tight tabular-nums">
                  <CountUp to={scene.value!} run={answered && !reduced} decimals={scene.id === "area" ? 2 : 0} />{" "}
                  <span className="text-base font-medium text-muted-foreground">{scene.unit}</span>
                </p>
              )}
            </div>
            <p className={cn("max-w-[52ch] text-sm leading-relaxed text-foreground/75 transition-opacity duration-500", answered ? "opacity-100" : "opacity-0")}>
              {scene.note}
            </p>

            {scene.evidence.length > 0 && (
              <ul className={cn("mt-auto flex flex-wrap gap-1.5 transition-opacity duration-500", answered ? "opacity-100" : "opacity-0")} aria-label="Evidence">
                {scene.evidence.map((e) => (
                  <li key={e.key}>
                    <button
                      type="button"
                      aria-pressed={picked === e.key}
                      onMouseEnter={() => setHover(e.key)}
                      onMouseLeave={() => setHover(null)}
                      onFocus={() => setHover(e.key)}
                      onBlur={() => setHover(null)}
                      onClick={() => choose(e.key)}
                      className={cn(
                        "flex items-center gap-2 rounded-md border px-2 py-1 text-left text-[13px] transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                        active === e.key ? "border-evidence bg-evidence-soft" : "hover:bg-muted",
                      )}
                    >
                      {scene.evidence.length > 1 && (
                        <span className="grid size-5 shrink-0 place-items-center rounded-full bg-evidence font-mono text-[11px] font-semibold text-white">
                          {e.key}
                        </span>
                      )}
                      {e.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
      <figcaption id="demo-cap" className="label mt-3 max-w-[70ch] leading-relaxed">
        Real output of stoa ask on a Swiss Dwellings floor plan. Drawing: Swiss Dwellings v3.0.0 by Archilyse AG, CC BY 4.0,
        rendered by the Junction organisers, not endorsed by the authors.
      </figcaption>
    </figure>
  )
}
