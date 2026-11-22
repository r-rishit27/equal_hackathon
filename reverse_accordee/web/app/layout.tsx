import type { Metadata } from "next";
import { Inter, Hedvig_Letters_Serif, Geist_Mono } from "next/font/google";
import { THEME_BOOT } from "@/components/shell/ShellProvider";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const hedvig = Hedvig_Letters_Serif({ subsets: ["latin"], variable: "--font-hedvig" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

export const metadata: Metadata = {
  title: { default: "Northstar", template: "%s · Northstar" },
  description: "AI-assisted CRM for B2B teams: customers, contracts and billing in one place.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${hedvig.variable} ${mono.variable}`}>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} /></head>
      <body className="h-full w-full overflow-hidden bg-appBg font-sans text-body text-textPrimary">{children}</body>
    </html>
  );
}
