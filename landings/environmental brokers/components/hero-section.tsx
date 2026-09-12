"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ArrowRight } from "lucide-react"

const enquiries = [
  {
    client: "Vane & Halsted Group plc",
    sector: "Manufacturing & Heavy Industrial",
    location: "Birmingham, UK",
    scope: "Scope 3 Value-Chain Emissions & Product Life Cycle Assessment",
    stage: "Stage 4",
    status: "Briefing Confirmed & Scoping Dossier Issued",
    statusColor: "text-primary",
    activity: "Decana engaged the inbound enquiry, parsed the 90-day compliance ultimatum, and flagged the threat to their £45M supply contract.",
  },
  {
    client: "Meridian Capital Partners LLP",
    sector: "Banking & Financial Services (Private Equity)",
    location: "London (Mayfair), UK",
    scope: "Ultra-Rapid 14-Day ESG Due Diligence (M&A Transaction)",
    stage: "Stage 5",
    status: "Awaiting Partner Technical Briefing",
    statusColor: "text-amber-500",
    activity: "Decana instantly flagged as Critical Urgency / High-Value Advisory Engagement. Estimated case value: £45,000.",
  },
  {
    client: "Avenis Consumer Brands SA",
    sector: "Retail & FMCG",
    location: "Geneva / London UK Retail Operations",
    scope: "Anti-Greenwashing Litigation Defense & SBTi Alignment",
    stage: "Stage 3",
    status: "Briefing Scheduled (Partner Calendar Locked)",
    statusColor: "text-primary",
    activity: "Decana parsed urgent request from corporate legal counsel regarding UK/EU anti-greenwashing directives.",
  },
  {
    client: "Solas Infrastructure Ltd",
    sector: "Energy & Civil Infrastructure",
    location: "Edinburgh, Scotland",
    scope: "Mandatory UK SDR Compliance & Double Materiality Assessment",
    stage: "Stage 2",
    status: "Scope Qualified (Framework Identified)",
    statusColor: "text-blue-400",
    activity: "Decana qualified that the firm has crossed statutory thresholds triggering mandatory UK SDR reporting.",
  },
  {
    client: "Kestrel Logistics Group",
    sector: "Global Supply Chain & Maritime Freight",
    location: "Rotterdam / UK Ports",
    scope: "Cross-Border CSRD Regulatory Reporting",
    stage: "Stage 1",
    status: "AI Scoping Active",
    statusColor: "text-cyan-400",
    activity: "LIVE INGESTION: Decana is actively interviewing caller to map 12 regional subsidiaries.",
    isLive: true,
  },
]

export function HeroSection() {
  const [currentEnquiryIndex, setCurrentEnquiryIndex] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)

  useEffect(() => {
    const interval = setInterval(() => {
      setIsAnimating(true)
      setTimeout(() => {
        setCurrentEnquiryIndex((prev) => (prev + 1) % enquiries.length)
        setIsAnimating(false)
      }, 300)
    }, 3500)

    return () => clearInterval(interval)
  }, [])

  const currentEnquiry = enquiries[currentEnquiryIndex]

  return (
    <section className="relative pt-32 pb-24 lg:pt-40 lg:pb-32">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        {/* Hero Content - Centered */}
        <div className="max-w-3xl mx-auto text-center mb-16 lg:mb-20">
          <Badge variant="outline" className="mb-6 border-primary/30 text-primary">
            <span className="mr-1.5">✦</span>
            AI-Powered Enquiry Automation
          </Badge>
          <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl lg:text-6xl text-balance leading-[1.1]">
            <span className="text-primary">Decana</span> Automates Complex ESG Enquiries.
          </h1>
          <p className="mt-4 text-xl text-muted-foreground/90 font-medium">
            Capture every instruction. Qualify every engagement. 24/7.
          </p>
          <p className="mt-6 text-lg leading-relaxed text-muted-foreground">
            Our AI-powered platform fields inbound corporate enquiries, qualifies technical scopes against your
            practice&apos;s exact expertise, and instantly structures complex regulatory requirements. Purpose-built 
            to help specialised UK sustainability and ESG advisory firms compete at scale without adding heavy 
            administrative overhead.
          </p>
          <div className="mt-10 flex flex-col sm:flex-row gap-4 justify-center">
            <Button
              variant="secondary"
              size="lg"
              className="text-secondary-foreground border border-border hover:bg-secondary/80"
            >
              View Platform Overview
            </Button>
            <Button asChild size="lg" className="bg-primary text-primary-foreground hover:bg-primary/90">
              <a href="#request-briefing">
                Request a Briefing
                <ArrowRight className="ml-2 h-4 w-4" />
              </a>
            </Button>
          </div>
        </div>

        {/* Live Dashboard Preview - Full Width at Bottom */}
        <div className="relative max-w-4xl mx-auto">
          <Card className="bg-card border-border/60 overflow-hidden">
            <div className="p-6 border-b border-border/60">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                  <span className="text-sm font-medium text-foreground">Live Ingestion Feed</span>
                </div>
                <span className="text-xs text-muted-foreground">Real-time</span>
              </div>
            </div>

            <div className="p-6 space-y-4">
              <div
                className={`transition-all duration-300 ${
                  isAnimating ? "opacity-0 translate-y-2" : "opacity-100 translate-y-0"
                }`}
              >
                <div className="space-y-3">
                  {/* Stage - Prominent at top */}
                  <div className="flex items-center justify-between pb-3 border-b border-border/40">
                    <span className="text-sm font-semibold uppercase tracking-wider text-primary">
                      {currentEnquiry.stage}
                    </span>
                    <Badge
                      variant="outline"
                      className={`${currentEnquiry.statusColor} border-current/30 text-xs`}
                    >
                      {currentEnquiry.isLive && (
                        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current animate-pulse inline-block" />
                      )}
                      {currentEnquiry.status}
                    </Badge>
                  </div>

                  {/* Client & Location */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs uppercase tracking-wider text-muted-foreground">
                        Client
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {currentEnquiry.client}
                      </span>
                    </div>
                    <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
                      <span>{currentEnquiry.sector}</span>
                      <span className="text-border">|</span>
                      <span>{currentEnquiry.location}</span>
                    </div>
                  </div>

                  {/* Scope */}
                  <div className="flex items-start justify-between pt-2 border-t border-border/40">
                    <span className="text-xs uppercase tracking-wider text-muted-foreground">
                      Engagement
                    </span>
                    <span className="text-sm font-medium text-foreground text-right max-w-[320px]">
                      {currentEnquiry.scope}
                    </span>
                  </div>

                  {/* Activity Log */}
                  <div className="pt-3 border-t border-border/40">
                    <span className="text-xs uppercase tracking-wider text-muted-foreground block mb-2">
                      Automation Activity
                    </span>
                    <p className="text-xs text-muted-foreground/80 leading-relaxed">
                      {currentEnquiry.activity}
                    </p>
                  </div>
                </div>
              </div>

              {/* Progress indicators */}
              <div className="pt-4 border-t border-border/40 flex gap-1.5">
                {enquiries.map((_, index) => (
                  <div
                    key={index}
                    className={`h-1 flex-1 rounded-full transition-colors ${
                      index === currentEnquiryIndex ? "bg-primary" : "bg-border"
                    }`}
                  />
                ))}
              </div>
            </div>
          </Card>

          {/* Decorative elements */}
          <div className="absolute -z-10 -top-8 -right-8 h-64 w-64 rounded-full bg-primary/5 blur-3xl" />
          <div className="absolute -z-10 -bottom-8 -left-8 h-48 w-48 rounded-full bg-primary/5 blur-3xl" />
        </div>
      </div>
    </section>
  )
}
