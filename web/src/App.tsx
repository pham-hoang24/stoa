import { Footer } from "@/components/site/Footer"
import { Header } from "@/components/site/Header"
import { Hero } from "@/components/site/Hero"
import { ScenarioShowcase } from "@/components/site/ScenarioShowcase"
import { Lanes } from "@/components/site/Lanes"
import { Measured } from "@/components/site/Measured"
import { Method } from "@/components/site/Method"
import { Notes } from "@/components/site/Notes"
import { Run } from "@/components/site/Run"
import { Why } from "@/components/site/Why"

export default function App() {
  return (
    <>
      <div className="grain" aria-hidden />
      <a
        href="#demo"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to demo
      </a>
      <Header />
      <main className="relative z-10">
        <Hero />
        <Why />
        <ScenarioShowcase />
        <Lanes />
        <Method />
        <Measured />
        <Run />
        <Notes />
      </main>
      <div className="relative z-10">
        <Footer />
      </div>
    </>
  )
}
