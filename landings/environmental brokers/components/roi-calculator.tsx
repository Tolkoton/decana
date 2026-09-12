"use client"

import { useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Slider } from "@/components/ui/slider"
import { Button } from "@/components/ui/button"
import { Calculator, ArrowRight } from "lucide-react"

export function ROICalculator() {
  const [missedPerMonth, setMissedPerMonth] = useState([4])
  const [averageEngagementValue, setAverageEngagementValue] = useState([25000])

  const CONVERSION_RATE = 0.05 // one in twenty

  const missedVal = missedPerMonth[0]
  const engagementVal = averageEngagementValue[0]

  const annualMissedEnquiries = missedVal * 12
  const lostFeeIncome = annualMissedEnquiries * CONVERSION_RATE * engagementVal

  const roundedFeeIncome = Math.round(lostFeeIncome / 1000) * 1000

  return (
    <section className="py-24 lg:py-32">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <h2 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl text-balance">
            What are the calls you miss actually costing you?
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Drag the sliders to your own numbers.
          </p>
        </div>

        <Card className="max-w-4xl mx-auto bg-card border-border/60">
          <CardHeader className="text-center">
            <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mx-auto mb-4">
              <Calculator className="h-6 w-6 text-primary" />
            </div>
            <CardTitle className="text-xl text-foreground">Missed Enquiry Calculator</CardTitle>
            <CardDescription className="text-muted-foreground">
              Adjust the sliders to estimate your lost opportunities
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-8">
            <div className="grid lg:grid-cols-2 gap-8 lg:gap-12">
              {/* Left Column - Interactive Inputs */}
              <div className="space-y-8 flex flex-col justify-center">
                {/* Missed Enquiries Slider */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-foreground">
                      Enquiries you miss each month
                    </label>
                    <span className="text-2xl font-semibold text-primary">{missedVal}</span>
                  </div>
                  <Slider
                    value={missedPerMonth}
                    onValueChange={setMissedPerMonth}
                    min={1}
                    max={15}
                    step={1}
                    className="w-full"
                  />
                  <p className="text-xs text-muted-foreground/80">
                    Calls that arrive while you are in a meeting, on a call, or out of hours.
                  </p>
                </div>

                {/* Engagement Value Slider */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-foreground">
                      Your average engagement value
                    </label>
                    <span className="text-2xl font-semibold text-primary">
                      £{engagementVal.toLocaleString("en-GB")}
                    </span>
                  </div>
                  <Slider
                    value={averageEngagementValue}
                    onValueChange={setAverageEngagementValue}
                    min={5000}
                    max={100000}
                    step={2500}
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>£5,000</span>
                    <span>£100,000</span>
                  </div>
                </div>
              </div>

              {/* Right Column - Dynamic Outputs */}
              <div className="space-y-6 flex flex-col justify-center">
                {/* Primary Output */}
                <div className="p-6 bg-primary/10 rounded-lg border border-primary/30 text-center lg:text-left">
                  <div className="text-sm text-muted-foreground mb-1">
                    Potential clients you never speak to each year
                  </div>
                  <div className="text-6xl font-bold text-primary tracking-tight">
                    {annualMissedEnquiries}
                  </div>
                </div>

                {/* Supporting Output with assumption connected directly to the money line */}
                <div className="p-6 bg-muted/50 rounded-lg border border-border/40 text-center lg:text-left space-y-3">
                  <p className="text-xs text-muted-foreground/80 leading-relaxed">
                    Assuming you would win one in {Math.round(1 / CONVERSION_RATE)} of the enquiries you never got to speak to.
                  </p>
                  <div className="border-t border-border/40 pt-3">
                    <div className="text-sm text-muted-foreground mb-1">
                      Fee income left on the table
                    </div>
                    <div className="text-3xl font-semibold text-foreground">
                      £{roundedFeeIncome.toLocaleString("en-GB")}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Bottom CTA */}
            <div className="pt-8 border-t border-border/60 text-center">
              <p className="text-muted-foreground mb-6">
                One recovered engagement covers Decana for years.
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
