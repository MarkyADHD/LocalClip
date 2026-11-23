import type { Metadata } from "next";
import { Geist, Geist_Mono, Syne } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LocalAutoSignIn } from "@/components/local-auto-sign-in";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const syne = Syne({
  variable: "--font-syne",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: { default: "LocalClip", template: "%s | LocalClip" },
  description: "Turn your streams into captioned short-form clips, on your own PC.",
  applicationName: "LocalClip",
  icons: { icon: "/icon.png" },
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // Dark by default, like the editors; Settings > Appearance can switch it (stored in localStorage).
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `try{if(localStorage.getItem("localclip-theme")==="light")document.documentElement.classList.remove("dark")}catch(e){}` }} />
      </head>
      <body className={`${geistSans.variable} ${geistMono.variable} ${syne.variable} antialiased`}>
        <TooltipProvider>
          <LocalAutoSignIn />
          {children}
          <Toaster />
        </TooltipProvider>
      </body>
    </html>
  );
}
