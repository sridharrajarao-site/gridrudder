import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export function generateMetadata(): Metadata {
  const canonical = "https://gridrudder.com";
  const socialImage = `${canonical}/og.png`;
  const title = "GridRudder — Make every watt work";
  const description = "Supervised GPU power orchestration with operator-approved actions and independent BMC verification.";
  return {
    metadataBase: new URL(canonical),
    title,
    description,
    alternates: { canonical },
    icons: { icon: [{ url: "/favicon.svg", type: "image/svg+xml" }, { url: "/favicon.ico", type: "image/x-icon" }], shortcut: "/favicon.ico" },
    openGraph: { title, description, url: canonical, type: "website", siteName: "GridRudder", images: [{ url: socialImage, width: 2048, height: 1080, alt: "GridRudder: Make every watt work" }] },
    twitter: { card: "summary_large_image", title, description, images: [socialImage] },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
