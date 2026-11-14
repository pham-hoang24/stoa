import { Badge } from "@/components/ui/badge"
import { area } from "@/data/evidence"
import { cn } from "@/lib/utils"

type Lane = {
  id: "ifc" | "swiss" | "vision" | "doc"
  title: string
  source: string
  body: string
  tags: string[]
  span: string
}

const LANES: Lane[] = [
  {
    id: "ifc",
    title: "IFC models",
    source: "ifc_models, ifc_bench",
    body: "IfcOpenShell reads quantities and the spatial structure straight from the model. A count is a list of element ids, so the evidence is exact.",
    tags: ["IfcOpenShell", "GlobalId evidence"],
    span: "lg:col-span-7",
  },
  {
    id: "swiss",
    title: "Swiss dwellings",
    source: "swiss_dwellings",
    body: "Rules run on the DXF sibling of each PDF. Room areas come from boundary polygons. No LLM is involved.",
    tags: ["Rules", "No LLM"],
    span: "lg:col-span-5",
  },
  {
    id: "vision",
    title: "Raster plans",
    source: "cubicasa5k",
    body: "Door and window counts come from detections on the PNG, numbered on the image. Provider calls are capped, and answer priors were removed so nothing is copied from reference answers.",
    tags: ["Detection", "Capped calls"],
    span: "lg:col-span-5",
  },
  {
    id: "doc",
    title: "Other documents",
    source: "all other sources",
    body: "An LLM reads page text and renders. It also takes over when the IFC lane abstains with a typed defer.",
    tags: ["LLM", "Fallback"],
    span: "lg:col-span-7",
  },
]

function Thumb({ id }: { id: Lane["id"] }) {
  const ink = "var(--forest-800)"
  const ev = "var(--evidence)"
  return (
    <svg viewBox="0 0 320 150" className="block h-full w-full" aria-hidden>
      <rect width="320" height="150" fill="var(--mist)" />
      {id === "ifc" && (
        <g fill="none" stroke={ink} strokeWidth="1.5" strokeLinejoin="round">
          <path d="M70 105 160 140 250 105 250 50 160 15 70 50Z" fill="var(--card)" />
          <path d="M70 50 160 85 250 50M160 85V140" />
          <path d="M110 70V108M205 72V110" stroke="var(--forest-600)" />
          <rect x="196" y="88" width="20" height="30" stroke={ev} strokeWidth="2" rx="2" />
          <rect x="100" y="86" width="20" height="30" stroke={ev} strokeWidth="2" rx="2" />
        </g>
      )}
      {id === "swiss" && (
        <svg viewBox="545 262 180 84.4" width="320" height="150" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Room 2.10 on a real Swiss Dwellings sheet with its boundary polygon">
          <rect x="545" y="262" width="180" height="85" fill="white" />
          <image href="/sheet.svg" x="0" y="0" width="1190.551" height="841.89" />
          <polygon points={area.points} fill={ev} fillOpacity="0.2" stroke={ev} strokeWidth="1.6" strokeLinejoin="round" />
        </svg>
      )}
      {id === "vision" && (
        <g>
          <g stroke="var(--sunken)" strokeWidth="1">
            {Array.from({ length: 17 }, (_, i) => (
              <path key={`v${i}`} d={`M${i * 20} 0V150`} />
            ))}
            {Array.from({ length: 8 }, (_, i) => (
              <path key={`h${i}`} d={`M0 ${i * 20}H320`} />
            ))}
          </g>
          <path d="M40 30H280V120H40Z M160 30V120" fill="none" stroke={ink} strokeWidth="3" />
          {[
            [160, 58, 1],
            [100, 120, 2],
            [220, 120, 3],
          ].map(([x, y, n]) => (
            <g key={n}>
              <rect x={x - 12} y={y - 12} width="24" height="24" fill="none" stroke={ev} strokeWidth="2" rx="2" />
              <circle cx={x - 12} cy={y - 12} r="8" fill={ev} />
              <text x={x - 12} y={y - 8.5} textAnchor="middle" fontSize="10" fontWeight="600" fill="white" className="font-mono">
                {n}
              </text>
            </g>
          ))}
        </g>
      )}
      {id === "doc" && (
        <g>
          <rect x="95" y="14" width="130" height="122" rx="3" fill="var(--card)" stroke={ink} strokeWidth="1.5" />
          {[34, 46, 58, 70, 94, 106].map((y, i) => (
            <rect key={y} x="110" y={y} width={i % 2 ? 88 : 100} height="5" rx="2" fill="var(--sunken)" />
          ))}
          <rect x="108" y="80" width="104" height="9" rx="2" fill="var(--evidence-soft)" stroke={ev} strokeWidth="1.5" />
        </g>
      )}
    </svg>
  )
}

export function Lanes() {
  return (
    <section id="lanes" className="border-t py-[clamp(4rem,9vw,8rem)]">
      <div className="wrap">
        <div className="grid gap-6 lg:grid-cols-[5fr_6fr] lg:items-end">
          <h2 className="text-[clamp(1.9rem,3.6vw,3rem)] leading-[1.05] font-semibold tracking-[-0.03em]">
            One lane per kind of drawing
          </h2>
          <p className="max-w-[52ch] text-base leading-relaxed text-foreground/75">
            A lane is the method Stoa uses for one kind of drawing. The dataset mixes IFC models, CAD sheets, scanned
            images and PDFs, so each lane uses the most exact method its source allows and returns the same kind of answer.
          </p>
        </div>

        <ul className="mt-12 grid gap-4 lg:grid-cols-12">
          {LANES.map((l) => (
            <li key={l.id} className={cn("group", l.span)}>
              <article className="flex h-full flex-col overflow-hidden rounded-xl border bg-card transition-shadow duration-300 hover:shadow-[0_18px_40px_-26px_#00000033]">
                <div className="h-48 overflow-hidden sm:h-56">
                  <div className="h-full transition-transform duration-500 ease-out-quart group-hover:scale-[1.03]">
                    <Thumb id={l.id} />
                  </div>
                </div>
                <div className="flex flex-1 flex-col gap-3 p-5">
                  <div className="flex items-baseline justify-between gap-4">
                    <h3 className="text-lg font-semibold tracking-tight">{l.title}</h3>
                    <span className="label shrink-0">lane {l.id}</span>
                  </div>
                  <p className="text-[15px] leading-relaxed text-foreground/75">{l.body}</p>
                  <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-2">
                    <span className="mr-1 font-mono text-xs text-muted-foreground">{l.source}</span>
                    {l.tags.map((t) => (
                      <Badge key={t} variant="outline" className="font-normal">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              </article>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
