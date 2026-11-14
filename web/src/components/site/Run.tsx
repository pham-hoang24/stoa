import { useRef, useState } from "react"
import { Check, Copy } from "lucide-react"
import { Button } from "@/components/ui/button"

const REPO = "https://github.com/pham-hoang24/stoa"
const SNIPPET = `uv sync
export STOA_DATASET=/path/to/junction-dataset
stoa serve`

export function Run() {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number>(0)

  async function copy() {
    try {
      await navigator.clipboard.writeText(SNIPPET)
      setCopied(true)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 1800)
    } catch {
      /* clipboard blocked: the text stays selectable */
    }
  }

  return (
    <section id="run" className="border-t bg-mist py-[clamp(4rem,9vw,8rem)]">
      <div className="wrap grid items-center gap-12 lg:grid-cols-[1fr_1fr] lg:gap-20">
        <div>
          <h2 className="text-[clamp(2.2rem,4.8vw,4rem)] leading-[1.02] font-semibold tracking-[-0.035em]">
            Take a question from the sheet to its source.
          </h2>
          <p className="mt-6 max-w-[44ch] text-lg leading-relaxed text-foreground/75">
            Run the local viewer, choose your drawing, ask a question and inspect its source. You can also try the verified Swiss Dwellings questions above before installing anything.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button render={<a href={REPO} />} nativeButton={false} className="h-11 rounded-full px-6 text-[15px]">
              Read the code
            </Button>
            <Button
              render={<a href={`${REPO}/blob/main/README.md#use`} />}
              nativeButton={false}
              variant="outline"
              className="h-11 rounded-full px-6 text-[15px]"
            >
              Open the setup guide
            </Button>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border bg-forest-950 text-primary-foreground">
          <div className="flex items-center justify-between border-b border-white/15 px-4 py-2.5">
            <span className="font-mono text-xs text-white/70">terminal · http://127.0.0.1:8765</span>
            <button
              type="button"
              onClick={copy}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-white/80 outline-none transition-colors hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-white/40"
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              <span aria-live="polite">{copied ? "Copied" : "Copy commands"}</span>
            </button>
          </div>
          <pre className="overflow-x-auto p-5 font-mono text-[13px] leading-7 text-white/90">
            <code>{SNIPPET}</code>
          </pre>
        </div>
      </div>
    </section>
  )
}
