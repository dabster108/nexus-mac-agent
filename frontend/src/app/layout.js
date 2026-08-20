import { Inter, Geist_Mono } from "next/font/google";
import "./globals.css";

/**
 * Inter for everything a person reads, Geist Mono for everything a machine
 * produced — paths, branches, ports, tool names. Keeping those two apart is
 * what lets a path sit inside a sentence without being mistaken for prose.
 */

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata = {
  title: "NEXUS",
  description: "A local AI operating layer for macOS.",
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="h-full">{children}</body>
    </html>
  );
}
