import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";

export const metadata: Metadata = {
  title: "多模型群聊",
  description: "在自己电脑上把已登录的网页 AI 接进同一个房间。默认不预置聊天，也不调用付费接口。",
  applicationName: "ChatCluster",
  appleWebApp: { capable: true, title: "ChatCluster", statusBarStyle: "black-translucent" },
  icons: { icon: "/icons/icon-192.png", apple: "/apple-touch-icon.png" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#1b1916",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="antialiased">
        <Script id="room-prefs" strategy="beforeInteractive">
          {`try{var t=localStorage.getItem("room-theme")||"system";var d=t==="dark"||(t==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);document.documentElement.dataset.text=localStorage.getItem("room-text")||"normal";}catch(e){}`}
        </Script>
        {children}
      </body>
    </html>
  );
}
