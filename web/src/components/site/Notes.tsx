import { ArrowUpRight } from "lucide-react"

const BASE = "https://github.com/pham-hoang24/stoa/blob/main/docs/adr"

const NOTES = [
  {
    no: "ADR 0001",
    title: "Route by source, not question type",
    body: "Why the router looks at where a drawing came from and its format, and what that buys in predictability.",
    href: `${BASE}/0001-route-by-source-not-question-type.md`,
  },
  {
    no: "ADR 0002",
    title: "Split dev and test by drawing",
    body: "Questions come in bilingual pairs and share drawings, so the split hashes the file path to stop answers leaking between dev and test.",
    href: `${BASE}/0002-split-dev-test-by-file.md`,
  },
  {
    no: "ADR 0003",
    title: "The Swiss lane uses rules, not an LLM",
    body: "Doors, windows and room areas are read exactly from the DXF sibling. The cost: the rules are fitted to the Swiss Dwellings export.",
    href: `${BASE}/0003-swiss-lane-uses-rules-not-an-llm.md`,
  },
]

export function Notes() {
  return (
    <section id="notes" className="py-[clamp(4rem,9vw,8rem)]">
      <div className="wrap">
        <h2 className="text-[clamp(1.9rem,3.6vw,3rem)] leading-[1.05] font-semibold tracking-[-0.03em]">
          Decisions worth reading
        </h2>
        <ul className="mt-12 grid gap-4 md:grid-cols-3">
          {NOTES.map((n) => (
            <li key={n.no}>
              <a
                href={n.href}
                className="group flex h-full flex-col justify-between gap-10 rounded-xl border bg-card p-6 outline-none transition-[box-shadow,border-color] duration-300 hover:border-forest-400 hover:shadow-[0_18px_40px_-26px_#00000033] focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <div>
                  <p className="label">{n.no}</p>
                  <h3 className="mt-4 text-xl leading-snug font-semibold tracking-tight">{n.title}</h3>
                  <p className="mt-3 text-[15px] leading-relaxed text-foreground/75">{n.body}</p>
                </div>
                <span className="inline-flex items-center gap-1 text-sm font-medium">
                  Read {n.no}
                  <ArrowUpRight className="size-4 transition-transform duration-300 ease-out-quart group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
