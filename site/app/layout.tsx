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
  const title = "GridRudder — Supervised GPU power orchestration";
  const description = "Supervised GPU power orchestration with attended operator confirmation and comparison with independent BMC whole-server telemetry.";
  return {
    metadataBase: new URL(canonical),
    title,
    description,
    alternates: { canonical },
    icons: { icon: [{ url: "/steered-grid.png", type: "image/png" }], shortcut: "/steered-grid.png" },
    openGraph: { title, description, url: canonical, type: "website", siteName: "GridRudder", images: [{ url: socialImage, width: 2048, height: 1080, alt: "GridRudder supervised GPU power orchestration" }] },
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
        <aside className="source-disclosure" aria-label="Open-source project">
          <span>OPEN-SOURCE LOCAL TOOLING</span>
          <p>The local agent, simulator, and safety tooling are available on GitHub. This does not represent a hosted or fleet-control product.</p>
          <a href="https://github.com/sridharrajarao-site/gridrudder">Review the source →</a>
        </aside>
      </body>
    </html>
  );
}
