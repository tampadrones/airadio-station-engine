import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Radio",
  description: "Always-on AI genre radio",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
