import { Navbar } from "@/components/navbar"
import { HeroSection } from "@/components/hero-section"
import { ProblemSolutionSection } from "@/components/problem-solution"
import { CapabilitiesShowcase } from "@/components/capabilities-showcase"
import { ROICalculator } from "@/components/roi-calculator"
import { Footer } from "@/components/footer"

export default function Page() {
  return (
    <main className="min-h-screen bg-background text-foreground relative">
      {/* Background with logo watermark */}
      <div 
        className="fixed inset-0 z-0 pointer-events-none"
        aria-hidden="true"
      >
        {/* Base texture overlay */}
        <div className="absolute inset-0 bg-[url('/logo.png')] bg-cover bg-center bg-no-repeat opacity-[0.03]" />
        {/* Noise texture */}
        <div className="absolute inset-0 bg-noise opacity-[0.4]" />
        {/* Radial gradient for depth */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,var(--background)_70%)]" />
      </div>
      
      {/* Content */}
      <div className="relative z-10">
        <Navbar />
        <HeroSection />
        <ProblemSolutionSection />
        <CapabilitiesShowcase />
        <ROICalculator />
        <Footer />
      </div>
    </main>
  )
}
