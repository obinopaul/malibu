import type { Metadata } from "next"
import { JetBrains_Mono, Manrope } from "next/font/google"
import "./globals.css"

const sans = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
})

const mono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: "NovaCalc X",
  description: "A beautiful advanced calculator built with Next.js.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  )
}
