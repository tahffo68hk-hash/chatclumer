import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";

export const metadata: Metadata = {
  title: "多模型群聊",
  description: "一个共享时间线的多模型聊天房间。演示回复会标明不是真实模型。",
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
