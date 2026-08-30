import type { Metadata } from "next";
import { Archivo, Instrument_Sans } from "next/font/google";
import "./globals.css";

/**
 * Archivo for display, Instrument Sans for everything else.
 *
 * The brief specified IBM Plex Mono for all data and labels. That was replacing
 * it: at the sizes this screen is read from — a projector, across a room, in
 * ninety seconds — a monospace sets too loose, too small and too mechanically
 * to be read quickly, and it made a rescue tool look like a terminal readout.
 * Instrument Sans is humanist, sets tight, and stays legible small. It is also
 * not Inter, which the brief rules out and was right to.
 *
 * Mono survives in exactly one place: `.tabular`, for figures that tick.
 */
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

const instrument = Instrument_Sans({
  variable: "--font-instrument",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Searchlight",
  description: "Don't search everywhere. Search where they could be.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${instrument.variable} h-full antialiased`}
      // Browser extensions stamp attributes onto <html> before React hydrates
      // (a password manager here adds `data-mbtss-nonce`), and React reports
      // the difference as a hydration mismatch on every load. Verified as
      // external: the server sends a clean <html lang class>, and a browser
      // with no extensions produces zero hydration messages.
      //
      // This suppresses attribute mismatches on THIS ELEMENT ONLY, one level
      // deep. It does not hide real hydration bugs anywhere in the app, which
      // is why it is safe to use here and nowhere else.
      suppressHydrationWarning
    >
      <body className="h-full">{children}</body>
    </html>
  );
}
