"use client"

import { useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Slider } from "@/components/ui/slider"
import { Button } from "@/components/ui/button"
import { Calculator, ArrowRight } from "lucide-react"

export function ROICalculator() {
  const [enquiriesPerMonth, setEnquiriesPerMonth] = useState([20])
  const [hoursPerLead, setHoursPerLead] = useState([4])

  // Calculations based on spec
  const annualHoursSaved = enquiriesPerMonth[0] * hoursPerLead[0] * 12
  const deliveryMarginProtected = annualHoursSaved * 150 // £150/hr baseline delivery cost
  const newMandatesUnlocked = Math.floor(annualHoursSaved / 40) // 40 hours per new client

  return (
    <section className="py-24 lg:py-32">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <h2 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl text-balance">
            Protect Your Margins. Expand Your Capacity.
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            See exactly how much fixed-fee project capacity Decana recovers for your practice by automating the administrative scoping phase.
          </p>
        </div>

        <Card className="max-w-4xl mx-auto bg-card border-border/60">
          <CardHeader className="text-center">
            <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mx-auto mb-4">
              <Calculator className="h-6 w-6 text-primary" />
            </div>
            <CardTitle className="text-xl text-foreground">Operational Efficiency Calculator</CardTitle>
            <CardDescription className="text-muted-foreground">
              Adjust the sliders to match your practice&apos;s current operations
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-8">
            <div className="grid lg:grid-cols-2 gap-8 lg:gap-12">
              {/* Left Column - Interactive Inputs */}
              <div className="space-y-8">
                {/* Enquiries Slider */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-foreground">
                      Monthly Inbound Corporate Enquiries
                    </label>
                    <span className="text-2xl font-semibold text-primary">{enquiriesPerMonth[0]}</span>
                  </div>
                  <Slider
                    value={enquiriesPerMonth}
                    onValueChange={setEnquiriesPerMonth}
                    min={5}
                    max={100}
                    step={5}
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>5</span>
                    <span>100</span>
                  </div>
                </div>

                {/* Hours Slider */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-foreground">
                      Hours Wasted on Manual Triage & Scoping (Per Lead)
                    </label>
                    <span className="text-2xl font-semibold text-primary">{hoursPerLead[0]}</span>
                  </div>
                  <Slider
                    value={hoursPerLead}
                    onValueChange={setHoursPerLead}
                    min={1}
                    max={10}
                    step={1}
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>1 hour</span>
                    <span>10 hours</span>
                  </div>
                </div>

                {/* Context Note */}
                <p className="text-xs text-muted-foreground leading-relaxed pt-4 border-t border-border/40">
                  Based on an average baseline delivery cost of £150/hr for internal consulting resources, and an average boutique fixed-fee mandate value of £25,000.
                </p>
              </div>

              {/* Right Column - Dynamic Outputs */}
              <div className="space-y-4">
                <div className="p-6 bg-muted/50 rounded-lg border border-border/40">
                  <div className="text-sm text-muted-foreground mb-2">
                    Admin Overhead Saved Annually
                  </div>
                  <div className="text-4xl font-semibold text-foreground">
                    {annualHoursSaved.toLocaleString()}
                    <span className="text-lg text-muted-foreground ml-2">Hours</span>
                  </div>
                </div>

                <div className="p-6 bg-primary/10 rounded-lg border border-primary/30">
                  <div className="text-sm text-muted-foreground mb-2">
                    Delivery Margins Protected
                  </div>
                  <div className="text-4xl font-semibold text-primary">
                    £{deliveryMarginProtected.toLocaleString()}
                  </div>
                </div>

                <div className="p-6 bg-muted/50 rounded-lg border border-border/40">
                  <div className="text-sm text-muted-foreground mb-2">
                    New Mandates Unlocked Annually
                  </div>
                  <div className="text-4xl font-semibold text-foreground">
                    {newMandatesUnlocked}
                    <span className="text-lg text-muted-foreground ml-2">Clients</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Bottom CTA */}
            <div className="pt-8 border-t border-border/60 text-center">
              <p className="text-muted-foreground mb-6">
                Stop burning delivery margins on manual intake.
              </p>
              <Button size="lg" className="bg-primary text-primary-foreground hover:bg-primary/90">
                Arrange a Technical Consultation
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
