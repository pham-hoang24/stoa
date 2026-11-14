import { EvidenceDemo } from "@/components/site/EvidenceDemo"

const FACTS: [string, string][] = [
  ["Reads", "IFC models, DXF and PDF sheets, PNG plans"],
  ["Returns", "A value, its unit and the evidence behind it"],
  ["When unsure", "Abstains instead of guessing"],
]

export function Hero() {
  return (
    <section id="top" className="relative pt-28 pb-[clamp(4rem,9vw,8rem)] sm:pt-36">
      <div className="wrap grid items-start gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="rise">
          <h1 className="text-[clamp(2.4rem,4.4vw,3.75rem)] leading-[1.04] font-semibold tracking-[-0.035em]">
            Quantities from drawings, with the evidence on the sheet.
          </h1>
          <p className="mt-7 max-w-[44ch] text-lg leading-relaxed text-foreground/75">
            Ask how many rooms are on a floor or how large one is. Stoa answers from the drawing's own data and marks what
            it used, so a person can check the answer in seconds.
          </p>

          <dl className="mt-10 max-w-md divide-y border-y">
            {FACTS.map(([k, v]) => (
              <div key={k} className="grid grid-cols-[6.5rem_1fr] gap-4 py-3 text-sm">
                <dt className="label pt-0.5">{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div id="demo" className="scroll-mt-20 lg:pt-4">
          <EvidenceDemo />
        </div>
      </div>
    </section>
  )
}
