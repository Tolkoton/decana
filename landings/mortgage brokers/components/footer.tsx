"use client"

import { useState } from "react"
import Image from "next/image"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ArrowRight } from "lucide-react"

const footerLinks = [
  { label: "Privacy Policy", href: "#" },
  { label: "Terms of Service", href: "#" },
  { label: "Data Security", href: "#" },
  { label: "UK Sovereign Cloud", href: "#" },
]

export function Footer() {
  const [email, setEmail] = useState("")

  return (
    <footer className="py-24 lg:py-32 border-t border-border/60">
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        {/* CTA Section */}
        <div className="text-center max-w-2xl mx-auto mb-16">
          <h2 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl text-balance">
            Arrange a Consultation
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Enter your corporate email for a confidential architecture overview and deployment consultation.
          </p>

          <form
            className="mt-8 flex flex-col sm:flex-row gap-4 max-w-md mx-auto"
            onSubmit={(e) => {
              e.preventDefault()
              // Handle form submission
            }}
          >
            <Input
              type="email"
              placeholder="Enter your corporate email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="flex-1 bg-muted/50 border-border/60 text-foreground placeholder:text-muted-foreground focus:border-primary"
              required
            />
            <Button
              type="submit"
              className="bg-primary text-primary-foreground hover:bg-primary/90"
            >
              Request Briefing
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </form>
        </div>

        {/* Footer Bottom */}
        <div className="pt-8 border-t border-border/40">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-4">
              <Image
                src="/logo-trimmed.png"
                alt="Decana Logo"
                width={220}
                height={146}
                className="h-14 w-auto opacity-90"
              />
              <div className="hidden sm:block border-l border-border/60 pl-4">
                <span className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
                  Enquiry Automation
                </span>
              </div>
            </div>

            <nav className="flex flex-wrap items-center justify-center gap-6">
              {footerLinks.map((link) => (
                <a
                  key={link.label}
                  href={link.href}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  {link.label}
                </a>
              ))}
            </nav>

            <p className="text-sm text-muted-foreground">
              © {new Date().getFullYear()} Decana. All rights reserved.
            </p>
          </div>

          <div className="mt-8 text-center">
            <p className="text-xs text-muted-foreground max-w-2xl mx-auto">
              Decana is fully compliant with UK GDPR and the Data Protection Act 2018. 
              Sovereign UK cloud deployment options available. All client data is processed in accordance 
              with UK data protection regulations. Zero-data retention models available for enterprise clients 
              requiring enhanced confidentiality.
            </p>
          </div>
        </div>
      </div>
    </footer>
  )
}
