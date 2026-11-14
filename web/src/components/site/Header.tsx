import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"

const NAV = [
  { href: "#demo", label: "Demo" },
  { href: "#scenarios", label: "Scenarios" },
  { href: "#lanes", label: "Lanes" },
  { href: "#method", label: "Method" },
  { href: "#measured", label: "Measured" },

]

export function Header() {
  const bar = useRef<HTMLDivElement>(null)
  const pct = useRef<HTMLSpanElement>(null)
  const head = useRef<HTMLElement>(null)

  // Scroll progress is written straight to the DOM so scrolling never re-renders React.
  useEffect(() => {
    let raf = 0
    const update = () => {
      raf = 0
      const max = document.documentElement.scrollHeight - window.innerHeight
      const p = max > 0 ? Math.min(1, window.scrollY / max) : 0
      bar.current?.style.setProperty("transform", `scaleX(${p})`)
      if (pct.current) pct.current.textContent = `${Math.round(p * 100)}%`
      head.current?.toggleAttribute("data-stuck", window.scrollY > 24)
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }
    update()
    window.addEventListener("scroll", onScroll, { passive: true })
    window.addEventListener("resize", onScroll, { passive: true })
    return () => {
      window.removeEventListener("scroll", onScroll)
      window.removeEventListener("resize", onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <header
      ref={head}
      className="group/head fixed inset-x-0 top-0 z-50 border-b border-transparent transition-colors duration-300 data-stuck:border-border data-stuck:bg-background/85 data-stuck:backdrop-blur-md"
    >
      <div className="wrap grid h-16 grid-cols-[1fr_auto] items-center gap-6 lg:grid-cols-[1fr_auto_1fr]">
        <a href="#top" className="flex items-baseline gap-3 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <span className="text-xl font-semibold tracking-tight">Stoa</span>
          <span className="hidden text-sm text-muted-foreground sm:inline">Quantity takeoff with evidence</span>
        </a>
        <nav aria-label="Primary" className="hidden items-center gap-7 lg:flex">
          {NAV.map((n) => (
            <a
              key={n.href}
              href={n.href}
              className="text-sm text-foreground/70 transition-colors hover:text-foreground focus-visible:text-foreground"
            >
              {n.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center justify-end gap-4">
          <span ref={pct} aria-hidden className="label hidden w-8 text-right tabular-nums sm:inline">
            0%
          </span>
          <Button render={<a href="#run" />} nativeButton={false} size="lg" className="h-9 rounded-full px-4">
            Run it locally
          </Button>
        </div>
      </div>
      <div
        ref={bar}
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-px origin-left scale-x-0 bg-forest-800"
      />
    </header>
  )
}
