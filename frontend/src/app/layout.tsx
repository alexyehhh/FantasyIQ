import type { Metadata } from "next";
import { Barlow_Condensed, Public_Sans } from "next/font/google";
import NavBar from "@/components/NavBar";
import "./globals.css";

const display = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

const sans = Public_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "FantasyIQ",
  description: "AI-powered fantasy sports intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable}`}>
      <body className="bg-bg font-sans text-ink antialiased">
        <NavBar />
        {children}
      </body>
    </html>
  );
}
