import type { Metadata } from "next";

import { SessionProvider } from "@/components/session/session-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "SpeakUp · 演讲训练原型",
  description: "一个用于模拟演讲、实时反馈和结果复盘的 Web 原型。",
  icons: {
    icon: "/brand/speakup-logo-pure.png",
    apple: "/brand/speakup-logo-pure.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full bg-slate-50 text-slate-950">
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
