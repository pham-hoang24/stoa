import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"

const ROWS = [
  { lane: "swiss", method: "Rules on DXF geometry, no LLM", baseline: "99.2%" },
  { lane: "ifc", method: "IfcOpenShell, ifc_models", baseline: "97.6%" },
  { lane: "vision", method: "Detections on PNG", baseline: "not gated" },
  { lane: "doc", method: "LLM over text and renders", baseline: "not gated" },
]

const FAQ = [
  {
    q: "Why abstain instead of giving a best guess?",
    a: "A wrong quantity that looks confident ends up in a takeoff. An abstain costs a person a minute. The lanes are tuned to prefer the second.",
  },
  {
    q: "Can an abstain be passed on?",
    a: "Every abstain carries a typed reason. A defer from the IFC lane moves the question to the document lane, which reads text and renders. A declined abstain, like a room that is not on the sheet, is final.",
  },
  {
    q: "Does every answer need an LLM?",
    a: "No. IFC and Swiss answers are computed from model data and geometry by rules. Only the doc lane relies on a language model, and the vision lane calls a provider for detections.",
  },
  {
    q: "What was wrong with answer priors?",
    a: "A prior is the most common answer to a question template, used in place of a model answer. It leaks reference answers into the score, so it is being removed from the vision lane.",
  },
]

export function Measured() {
  return (
    <section id="measured" className="py-[clamp(4rem,9vw,8rem)]">
      <div className="wrap grid gap-14 lg:grid-cols-[6fr_5fr] lg:gap-20">
        <div>
          <h2 className="max-w-[16ch] text-[clamp(1.9rem,3.6vw,3rem)] leading-[1.05] font-semibold tracking-[-0.03em]">
            Measured against ground truth
          </h2>
          <p className="mt-5 max-w-[50ch] text-base leading-relaxed text-foreground/75">
            Two lanes have a regression gate that runs without any LLM. It compares answers with ground-truth questions and
            fails the build if accuracy drops below the recorded baseline.
          </p>

          <div className="mt-10 overflow-x-auto">
            <table className="w-full min-w-[28rem] border-collapse text-left text-sm">
              <caption className="sr-only">Lane, method and recorded gate baseline</caption>
              <thead>
                <tr className="label border-b">
                  <th scope="col" className="py-3 pr-4 font-normal">Lane</th>
                  <th scope="col" className="py-3 pr-4 font-normal">Method</th>
                  <th scope="col" className="py-3 text-right font-normal">Gate baseline</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map((r) => (
                  <tr key={r.lane} className="border-b">
                    <th scope="row" className="py-4 pr-4 font-mono text-[13px] font-medium">{r.lane}</th>
                    <td className="py-4 pr-4 text-foreground/80">{r.method}</td>
                    <td className="py-4 text-right font-medium tabular-nums">
                      {r.baseline === "not gated" ? (
                        <span className="font-normal text-muted-foreground">{r.baseline}</span>
                      ) : (
                        r.baseline
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="label mt-4 max-w-[60ch] leading-relaxed">
            Recorded in src/stoa/eval/baseline.json. Baselines are floors set by the gate, not final scores.
          </p>
        </div>

        <div>
          <h3 className="mb-2 text-xl font-semibold tracking-tight">How it handles not knowing</h3>
          <Accordion defaultValue={[FAQ[0].q]} className="mt-4">
            {FAQ.map((f) => (
              <AccordionItem key={f.q} value={f.q}>
                <AccordionTrigger className="py-4 text-base font-medium">{f.q}</AccordionTrigger>
                <AccordionContent className="text-[15px] leading-relaxed text-foreground/75">{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </div>
    </section>
  )
}
