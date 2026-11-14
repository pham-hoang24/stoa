import { useEffect, useState } from "react"
import { ArrowRight, CheckCircle2, FileImage, FileSearch2, Layers3, Pause, Play, ShieldAlert } from "lucide-react"
import { cn } from "@/lib/utils"

type ScenarioId = "ifc" | "raster" | "document"
type Scenario = {
  id: ScenarioId
  label: string
  source: string
  question: string
  method: string
  answer: string
  explanation: string
  limitation: string
}
const SCENARIOS: Scenario[] = [
  {
    id: "ifc",
    label: "IFC model",
    source: "IFC · structured model",
    question: "Which elements support this floor?",
    method: "IfcOpenShell → elements → GlobalIds",
    answer: "Element references",
    explanation: "Select an element to reveal the identifier stored in the source model.",
    limitation: "Illustrative workflow — not a structural-capacity assessment.",
  },
  {
    id: "raster",
    label: "Raster drawing",
    source: "PNG · image inspection",
    question: "How many windows are visible?",
    method: "Image regions → candidate detections → human review",
    answer: "3 candidates · unreviewed",
    explanation: "The model proposes highlighted regions. The count is not accepted until the full image is reviewed.",
    limitation: "Illustrative candidates, not a verified count or accuracy claim.",
  },
  {
    id: "document",
    label: "PDF sheet",
    source: "PDF · text and page rendering",
    question: "Where does this sheet specify the finish?",
    method: "Page text → matching source region",
    answer: "Source region located",
    explanation: "Show the excerpt in context, with a direct route back to its page.",
    limitation: "Illustrative lookup — check source language and page references.",
  },
]

function SceneDrawing({ id, stage }: { id: ScenarioId; stage: number }) {
  const highlighted = stage >= 2
  return (
    <svg viewBox="0 0 520 340" className="block w-full" role="img" aria-label={
      id === "ifc" ? "Isometric building frame with one selected IFC element" :
      id === "raster" ? "Floor plan with three proposed window detections" :
      "Document page with a selected technical specification excerpt"
    }>
      <rect width="520" height="340" rx="8" fill="var(--mist)" />
      {id === "ifc" && (
        <g strokeLinecap="round" strokeLinejoin="round">
          <g fill="none" stroke="var(--forest-800)" strokeWidth="2.2">
            <path d="M95 120 270 50 425 118 253 193Z M95 120V239L253 311V193 M253 311 425 238V118" />
            <path d="M95 179 253 251 425 178 M147 99 303 169 303 285 M199 78 353 149 353 263 M270 50V170" opacity=".55" />
            <path d="M145 142V262 M200 168V287 M305 171V289 M371 145V261" />
          </g>
          <path d="M200 168V287" fill="none" stroke="var(--evidence)" strokeWidth={highlighted ? 10 : 0} opacity=".6" className={cn(highlighted && "scenario-highlight")} />
          <path d="M200 168V287" fill="none" stroke="var(--evidence)" strokeWidth={highlighted ? 4 : 0} />
          {highlighted && <g className="scenario-pop"><rect x="207" y="211" width="145" height="35" rx="5" fill="var(--forest-950)" /><text x="219" y="233" fontSize="12" fill="white" fontFamily="monospace">IfcColumn · ID</text></g>}
          <text x="20" y="33" fontSize="12" fill="var(--forest-800)" fontFamily="monospace">MODEL / ELEMENT VIEW</text>
        </g>
      )}
      {id === "raster" && (
        <g>
          <path d="M74 52H436V292H74Z M230 52V292 M74 177H436 M329 177V292" fill="none" stroke="var(--forest-800)" strokeWidth="6" />
          <path d="M110 52H172 M275 52H338 M436 216V259" stroke="#78a9be" strokeWidth="8" />
          <path d="M230 210h27a27 27 0 0 1-27 27 M329 200h-26a26 26 0 0 0 26 26" stroke="var(--forest-700)" strokeWidth="1.8" fill="none" />
          <g fill="var(--muted-foreground)" fontSize="12"><text x="113" y="111">ROOM A</text><text x="288" y="111">ROOM B</text><text x="119" y="231">ROOM C</text><text x="354" y="241">ROOM D</text></g>
          {highlighted && [[110,42,62,20],[275,42,63,20],[425,216,20,43]].map(([x,y,w,h],i) => (
            <g key={i} className="scenario-pop" style={{ animationDelay: `${i * 120}ms` }}>
              <rect x={x} y={y} width={w} height={h} rx="2" fill="var(--evidence-soft)" fillOpacity=".7" stroke="var(--evidence)" strokeWidth="2.5" />
              <circle cx={x} cy={y} r="11" fill="var(--evidence)" /><text x={x} y={y+4} fontSize="12" textAnchor="middle" fill="white">{i+1}</text>
            </g>
          ))}
          <text x="20" y="33" fontSize="12" fill="var(--forest-800)" fontFamily="monospace">IMAGE / REVIEW CANDIDATES</text>
        </g>
      )}
      {id === "document" && (
        <g>
          <rect x="109" y="22" width="303" height="296" rx="3" fill="white" stroke="var(--sunken)" strokeWidth="2"/>
          <text x="130" y="49" fontSize="10" fontFamily="monospace" fill="var(--forest-800)">SHEET A-204 · FINISH NOTES</text>
          <path d="M130 60H391" stroke="var(--sunken)" />
          {[86,105,124,143,162,181,200,239,258,277].map((y,i)=><rect key={y} x="132" y={y} width={i%3===0?180:245} height="5" rx="2" fill="var(--sunken)"/>)}
          {highlighted && <g className="scenario-pop"><rect x="125" y="151" width="273" height="42" rx="3" fill="var(--evidence-soft)" stroke="var(--evidence)" strokeWidth="2"/><text x="138" y="177" fontSize="12" fill="var(--forest-950)" fontFamily="monospace">MATCHING SOURCE EXCERPT</text></g>}
          <text x="20" y="33" fontSize="12" fill="var(--forest-800)" fontFamily="monospace">PAGE / SOURCE REGION</text>
        </g>
      )}
    </svg>
  )
}

export function ScenarioShowcase() {
  const [active, setActive] = useState<ScenarioId>("ifc")
  const [stage, setStage] = useState(3)
  const [playing, setPlaying] = useState(false)
  const [reduced, setReduced] = useState(false)
  const scene = SCENARIOS.find((s) => s.id === active)!

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)")
    const sync = () => setReduced(media.matches)
    sync()
    media.addEventListener("change", sync)
    return () => media.removeEventListener("change", sync)
  }, [])

  useEffect(() => {
    if (!playing || reduced) { setStage(3); return }
    setStage(0)
    const timers = [700, 1500, 2700].map((ms,i)=>window.setTimeout(()=>setStage(i+1), ms))
    const done = window.setTimeout(()=>setPlaying(false), 4400)
    return () => { timers.forEach(window.clearTimeout); window.clearTimeout(done) }
  }, [active, playing, reduced])

  function select(id: ScenarioId) {
    setActive(id)
    setPlaying(!reduced)
    if (reduced) setStage(3)
  }

  return (
    <section id="scenarios" className="border-t py-[clamp(4rem,9vw,8rem)]" aria-labelledby="scenario-heading">
      <div className="wrap">
        <div className="grid items-end gap-7 lg:grid-cols-[6fr_5fr] lg:gap-20">
          <h2 id="scenario-heading" className="max-w-[18ch] text-[clamp(2.1rem,4vw,3.5rem)] leading-[1.05] font-semibold tracking-[-0.035em]">
            One question. A different way to find its evidence.
          </h2>
          <p className="max-w-[58ch] text-lg leading-relaxed text-foreground/75">
            Models, images and documents do not carry the same information. Explore how the interface changes its evidence to match the file instead of pretending every answer is equally certain.
          </p>
        </div>

        <div className="mt-11 overflow-hidden rounded-xl border bg-card shadow-[0_20px_50px_-35px_#00000040]">
          <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3 sm:px-6">
            <div className="flex flex-wrap gap-2" role="group" aria-label="Select an evidence scenario">
              {SCENARIOS.map((s) => (
                <button key={s.id} type="button" aria-pressed={active === s.id} onClick={()=>select(s.id)}
                  className={cn("rounded-full border px-4 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",active===s.id?"border-forest-950 bg-forest-950 text-white":"hover:bg-muted")}>
                  {s.label}
                </button>
              ))}
            </div>
            <button type="button" className="ml-auto inline-flex items-center gap-1.5 rounded-full border px-3 py-2 text-sm focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={()=>{setStage(0);setPlaying(true)}} disabled={playing||reduced} aria-label="Replay selected scenario">
              {playing?<Pause className="size-4"/>:<Play className="size-4"/>}{playing?"Playing":"Replay"}
            </button>
          </div>
          <div className="grid lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
            <div className="flex min-w-0 items-center justify-center border-b bg-mist p-4 lg:border-r lg:border-b-0 sm:p-8">
              <div key={active} className="w-full max-w-[650px]"><SceneDrawing id={active} stage={stage}/></div>
            </div>
            <div className="flex flex-col p-6 sm:p-9">
              <div className="mb-6 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                {active==="ifc"?<Layers3 className="size-4"/>:active==="raster"?<FileImage className="size-4"/>:<FileSearch2 className="size-4"/>}
                <span className="font-mono">{scene.source}</span>
              </div>
              <p className="label mb-2">Question</p>
              <p className="text-[clamp(1.2rem,2vw,1.6rem)] leading-snug font-semibold">{scene.question}</p>
              <div className={cn("my-6 flex items-center gap-2 text-sm transition-all duration-500",stage>=1?"opacity-100":"translate-y-1 opacity-0")}>
                <span className="rounded-md bg-mist px-3 py-2 font-mono text-xs leading-relaxed">{scene.method}</span><ArrowRight className="size-4 shrink-0 text-muted-foreground"/>
              </div>
              <div className={cn("rounded-lg p-4 transition-all duration-500",active==="raster"?"bg-evidence-soft":"bg-mist",stage>=3?"opacity-100":"translate-y-2 opacity-0")}>
                <p className="label mb-2">{active==="raster"?"Review required":"Demonstrated evidence"}</p>
                <p className="text-2xl font-semibold tracking-tight">{scene.answer}</p>
              </div>
              <p className="mt-5 text-[15px] leading-relaxed text-foreground/80">{scene.explanation}</p>
              <div className="mt-auto flex items-start gap-2 border-t pt-6 text-xs leading-relaxed text-muted-foreground">
                {active==="raster"?<ShieldAlert className="mt-0.5 size-4 shrink-0 text-evidence"/>:<CheckCircle2 className="mt-0.5 size-4 shrink-0"/>}
                <span>{scene.limitation}</span>
              </div>
            </div>
          </div>
        </div>
        <p className="label mt-4 max-w-[90ch] leading-relaxed">These three motion scenarios illustrate interface behavior, not benchmark outputs. The live, source-verified Swiss Dwellings examples remain in the hero above.</p>
      </div>
    </section>
  )
}
