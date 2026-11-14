export function Footer() {
  return (
    <footer className="border-t py-10">
      <div className="wrap flex flex-col gap-6 text-sm sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-lg font-semibold tracking-tight">Stoa</p>
          <p className="mt-1 text-muted-foreground">Built at Junction 2026 by pham-hoang24 and z0rhan.</p>
        </div>
        <ul className="flex flex-wrap gap-x-6 gap-y-2">
          <li>
            <a className="underline-offset-4 hover:underline" href="https://github.com/pham-hoang24/stoa">
              GitHub repository
            </a>
          </li>
          <li>
            <a className="underline-offset-4 hover:underline" href="https://github.com/pham-hoang24/stoa/blob/main/GLOSSARY.md">
              Glossary
            </a>
          </li>
          <li>
            <a className="underline-offset-4 hover:underline" href="#top">
              Back to top
            </a>
          </li>
        </ul>
      </div>
      <p className="wrap label mt-8 max-w-[90ch] leading-relaxed">
        Floor plan in the demo: Swiss Dwellings v3.0.0 by Archilyse AG (doi 10.5281/zenodo.7788422), CC BY 4.0, rendered by
        the Junction organisers, not endorsed by the authors. Visual language adapted from stoabuild.com and
        ulrychkristian.cz.
      </p>
    </footer>
  )
}
