import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Clock, FileText, Network } from "lucide-react"

const solutions = [
  {
    icon: Clock,
    problem: "24/7 Voice & Multi-Channel Ingest",
    solution:
      "Decana intercepts every incoming call instantly. If a corporate lead reaches out out-of-hours, the AI agent uses automated WhatsApp and SMS workflows to instantly engage the prospect, preventing premium instructions from dropping off to competitors.",
  },
  {
    icon: FileText,
    problem: "Automated Scoping & Triage",
    solution:
      "Stop chasing basic discovery details. Decana interactively profiles the enquirer's industry, regulatory deadlines, and framework requirements (like CSRD or Scope 3). The system flawlessly schedules the initial briefing and issues structured briefing dossiers so you know everything you need to before the first human call.",
  },
  {
    icon: Network,
    problem: "Native Practice Workflow Integration",
    solution:
      "Decana works invisibly alongside your existing software stack. Every step of the triage lifecycle is fully documented, audit-ready, and dynamically synced with your internal core workflows, letting your senior partners focus exclusively on high-value billable client delivery.",
  },
]

export function ProblemSolutionSection() {
  return (
    <section id="solutions" className="py-24 lg:py-32">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <h2 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl text-balance">
            Transform Inbound Friction into Operational Efficiency
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Boutique ESG practices face intense administrative bottlenecks. Decana automates the entire intake, triage, and scheduling lifecycle at the source.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6 lg:gap-8">
          {solutions.map((item, index) => (
            <Card
              key={index}
              className="bg-card border-border/60 hover:border-primary/30 transition-colors duration-300"
            >
              <CardHeader>
                <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                  <item.icon className="h-6 w-6 text-primary" />
                </div>
                <CardTitle className="text-xl text-foreground">{item.problem}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-muted-foreground text-base leading-relaxed">
                  {item.solution}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  )
}
