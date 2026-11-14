const STEPS = [
  {
    title: "Question",
    body: "A plain-language request about one drawing: a count, an area, a length. Questions come in English and in the drawing's own language.",
  },
  {
    title: "Router",
    body: "Picks the method from where the drawing came from and its file format, never from the wording of the question. The same drawing always gets the same method.",
  },
  {
    title: "Answer",
    body: "The method returns a value, a unit and its evidence, or it abstains. An abstain can pass the question to the document reader; a declined one stays declined.",
  },
  {
    title: "Viewer",
    body: "Draws the evidence on the sheet: a polygon on a room, a box on a PDF page, or an IFC element. A person clicks it and confirms.",
  },
]

export function Method() {
  return (
    <section id="method" className="border-t bg-forest-950 py-[clamp(4rem,9vw,8rem)] text-primary-foreground">
      <div className="wrap">
        <h2 className="max-w-[22ch] text-[clamp(1.9rem,3.6vw,3rem)] leading-[1.05] font-semibold tracking-[-0.03em]">
          From question to checked answer
        </h2>

        <ol className="mt-14 grid gap-x-10 gap-y-10 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="border-t border-white/20 pt-5">
              <p className="font-mono text-sm text-moss">{String(i + 1).padStart(2, "0")}</p>
              <h3 className="mt-6 text-xl font-semibold tracking-tight">{s.title}</h3>
              <p className="mt-3 max-w-[34ch] text-[15px] leading-relaxed text-white/75">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
