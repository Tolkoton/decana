import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Check } from "lucide-react"

const checklistItems = [
  "Continuous multi-channel engagement (Voice, SMS, and WhatsApp)",
  "Real-time technical framework & regulatory deadline identification",
  "Automated partner calendar coordination and interactive booking loops",
  "Comprehensive, audit-ready scoping dossiers delivered straight to your team",
  "Seamless background integration into your existing practice management software",
]

export function CapabilitiesShowcase() {
  return (
    <section id="how-it-works" className="py-24 lg:py-32 bg-muted/30">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <h2 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl text-balance">
            The Intelligent Advisory Intake Engine
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            From raw corporate enquiry to fully documented instruction—completely automated.
          </p>
        </div>

        {/* Main Feature Card */}
        <Card id="compliance" className="bg-card border-border/60 p-8 lg:p-12 max-w-4xl mx-auto">
          <div className="space-y-8">
            {/* Badge & Header */}
            <div>
              <Badge variant="outline" className="mb-4 border-primary/30 text-primary">
                Native Multi-Channel Automation
              </Badge>
              <h3 className="text-2xl font-semibold text-foreground">
                Flawless Inbound Triage & Engagement
              </h3>
            </div>

            {/* Body Copy */}
            <p className="text-muted-foreground leading-relaxed text-base">
              Decana acts as your always-on digital practice assistant, intercepting every incoming 
              corporate enquiry instantly across voice, SMS, and WhatsApp. The engine interactively 
              profiles the caller&apos;s specific industry sector, uncovers their core regulatory pain 
              points (such as CSRD timelines or Scope 3 supply chain mandates), and cross-references 
              their urgency against your practice&apos;s specialisms. It completely automates the 
              administrative scheduling loop, logs an audit-ready data trail, and issues comprehensive 
              pre-call scoping dossiers directly to your partners—ensuring you hold all the leverage 
              before the very first briefing call.
            </p>

            {/* Checklist */}
            <div className="pt-6 border-t border-border/40">
              <ul className="space-y-4">
                {checklistItems.map((item, i) => (
                  <li key={i} className="flex items-start gap-3 text-foreground">
                    <div className="h-5 w-5 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Check className="h-3 w-3 text-primary" />
                    </div>
                    <span className="text-sm leading-relaxed">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      </div>
    </section>
  )
}
