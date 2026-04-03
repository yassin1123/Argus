import type { Metadata } from "next";
import Link from "next/link";
import { DM_Sans, DM_Serif_Display } from "next/font/google";
import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  weight: ["400", "500", "600", "700"],
});

const dmSerif = DM_Serif_Display({
  subsets: ["latin"],
  variable: "--font-dm-serif",
  weight: "400",
});

export const metadata: Metadata = {
  title: "Argus",
  description: "Evidence-grounded decision intelligence",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${dmSans.variable} ${dmSerif.variable}`}>
      <body className={`min-h-screen font-sans ${dmSans.className}`}>
        <header className="sticky top-0 z-50 h-14 border-b border-argus-border-subtle bg-canvas/90 backdrop-blur-sm">
          <div className="mx-auto flex h-full max-w-[1600px] items-center justify-between px-6">
            <Link href="/" className="font-serif text-xl text-argus-primary">
              Argus
            </Link>
            <nav className="flex items-center gap-1">
              <Link
                href="/"
                className="rounded-argus-sm px-2.5 py-1.5 text-[13px] font-medium text-argus-secondary transition-colors duration-150 hover:bg-elevated hover:text-argus-primary"
              >
                New
              </Link>
              <Link
                href="/sessions"
                className="rounded-argus-sm px-2.5 py-1.5 text-[13px] font-medium text-argus-secondary transition-colors duration-150 hover:bg-elevated hover:text-argus-primary"
              >
                Sessions
              </Link>
            </nav>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
