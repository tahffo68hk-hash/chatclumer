import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "多模型群聊",
  description: "一个共享时间线的多模型聊天房间。演示回复会标明不是真实模型。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
