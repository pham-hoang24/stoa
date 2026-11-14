export function Why() {
  return (
    <section id="why" className="border-t py-[clamp(4rem,9vw,8rem)]">
      <div className="wrap grid gap-8 lg:grid-cols-[4fr_7fr] lg:gap-16">
        <h2 className="text-[clamp(1.9rem,3.6vw,3rem)] leading-[1.05] font-semibold tracking-[-0.03em]">
          A takeoff is only as good as the count behind it
        </h2>
        <div className="max-w-[58ch] space-y-5 text-lg leading-relaxed text-foreground/80">
          <p>
            Estimators count doors and windows and measure room areas from drawings to price a building. The counting is done
            by hand, one drawing at a time, and a wrong number looks the same as a right one until someone recounts.
          </p>
          <p>
            Stoa answers the same questions from the model or the geometry, then draws its evidence on the sheet. Checking an
            answer takes a click on the room instead of a recount of the floor.
          </p>
        </div>
      </div>
    </section>
  )
}
