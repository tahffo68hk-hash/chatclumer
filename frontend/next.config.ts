import os from "node:os";
import type { NextConfig } from "next";

// 手机模式（LAN=1）下用开发服务器时，手机从局域网 IP 访问 /_next 资源。认证在
// server/mobile-auth.mjs 里已经做过，这里只是告诉 Next 这些来源是本机自己的地址。
function localOrigins() {
  const out = new Set(["127.0.0.1", "localhost"]);
  for (const list of Object.values(os.networkInterfaces())) {
    for (const item of list || []) {
      if (item.family === "IPv4" && !item.internal) out.add(item.address);
    }
  }
  return [...out];
}

const nextConfig: NextConfig = {
  allowedDevOrigins: localOrigins(),
  // 开发角标在手机竖屏上会盖住底部导航。
  devIndicators: false,
};

export default nextConfig;
