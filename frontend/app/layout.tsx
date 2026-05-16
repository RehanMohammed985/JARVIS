import type { Metadata } from "next";
import { Exo_2, Inter, Orbitron } from "next/font/google";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const orbitron = Orbitron({
  subsets: ["latin"],
  variable: "--font-orbitron",
  weight: ["400", "500", "600", "700"],
});

const exo2 = Exo_2({
  subsets: ["latin"],
  variable: "--font-exo",
  weight: ["100", "200", "300", "400", "500", "600"],
});

export const metadata: Metadata = {
  title: "J.A.R.V.I.S.",
  description: "Local holographic command interface",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`h-full ${inter.variable} ${orbitron.variable} ${exo2.variable} font-sans`}
      style={{ backgroundColor: "#02040a", colorScheme: "dark" }}
    >
      <body
        className="min-h-full antialiased text-white"
        style={{
          margin: 0,
          minHeight: "100%",
          backgroundColor: "#02040a",
          color: "#ffffff",
        }}
      >
        {children}
      </body>
    </html>
  );
}
