"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// 「手机连接」面板。数据来自 /m/info，那个接口只回应电脑本机（回环地址 + 回环 Host），
// 手机上请求会得到 403，所以手机上不会出现这个按钮，口令也不会离开电脑。
export type MobileInfo = {
  lan: boolean;
  port: number;
  version: string;
  has_token: boolean;
  addresses: { ip: string; iface: string; kind: "lan" | "tailscale"; base: string; app_payload: string | null; web_link: string | null }[];
};

export function useMobileInfo() {
  const [info, setInfo] = useState<MobileInfo | null>(null);
  const load = useCallback(async () => {
    try {
      const res = await fetch("/m/info", { cache: "no-store" });
      if (res.ok) setInfo(await res.json());
      else setInfo(null);
    } catch {
      setInfo(null);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return { info, setInfo, reload: load };
}

function maskLink(link: string) {
  return link.replace(/([?&](?:token|t)=)[^&]+/, "$1••••••••");
}

export function MobileConnect({ open, onOpenChange, info, setInfo }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  info: MobileInfo | null;
  setInfo: (info: MobileInfo) => void;
}) {
  const [index, setIndex] = useState(0);
  const [kind, setKind] = useState<"app" | "web">("app");
  const [reveal, setReveal] = useState(false);
  const [svg, setSvg] = useState("");
  const [note, setNote] = useState("");
  const addr = info?.addresses[Math.min(index, Math.max(0, (info?.addresses.length || 1) - 1))];
  const payload = useMemo(() => (kind === "app" ? addr?.app_payload : addr?.web_link) || "", [addr, kind]);

  useEffect(() => {
    if (!open) {
      setReveal(false);
      setNote("");
    }
  }, [open]);

  useEffect(() => {
    let live = true;
    if (!payload) {
      setSvg("");
      return;
    }
    void QRCode.toString(payload, { type: "svg", margin: 1, errorCorrectionLevel: "M", color: { dark: "#1b1916", light: "#ffffff" } }).then((out) => {
      if (live) setSvg(out);
    });
    return () => {
      live = false;
    };
  }, [payload]);

  async function rotate() {
    if (!window.confirm("更换口令后，已经配对的手机都要重新扫码。确定更换？")) return;
    const res = await fetch("/m/rotate", { method: "POST", headers: { "X-CC-Local": "1" } });
    if (res.ok) {
      setInfo(await res.json());
      setReveal(false);
      setNote("已更换口令，旧的配对已失效。");
    } else {
      setNote("更换失败，请在电脑本机上操作。");
    }
  }

  async function copy() {
    if (!addr?.web_link) return;
    try {
      await navigator.clipboard.writeText(addr.web_link);
      setNote("配对链接已复制。它等同于钥匙，只发给自己的手机。");
    } catch {
      setNote("复制失败，请改用二维码。");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="mobile-panel" className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>手机连接</DialogTitle>
          <DialogDescription>手机和电脑在同一个 Wi-Fi（或都登录 Tailscale）时，扫码即可在手机上使用。网页 AI 仍然在这台电脑上运行，电脑要保持开机。</DialogDescription>
        </DialogHeader>
        {!info ? (
          <p className="text-sm text-[#6b6258]">读取中…</p>
        ) : !info.lan ? (
          <div data-testid="mobile-off" className="space-y-2 text-sm">
            <p>手机模式没有开启。现在只监听 127.0.0.1，手机连不上。</p>
            <p>先停止，再用手机模式启动：</p>
            <pre className="overflow-x-auto rounded-lg bg-[#1b1916] p-3 text-xs text-[#f6f1e8]">{"LAN=1 ./scripts/start.sh\n# Windows PowerShell：\n$env:LAN=\"1\"; .\\scripts\\start.ps1"}</pre>
          </div>
        ) : info.addresses.length === 0 ? (
          <p data-testid="mobile-noaddr" className="text-sm">没检测到局域网或 Tailscale 地址。确认电脑已连上 Wi-Fi，或已登录 Tailscale。</p>
        ) : (
          <div className="grid gap-3 text-sm">
            <div className="flex flex-wrap gap-2" data-testid="mobile-addrs">
              {info.addresses.map((item, i) => (
                <button
                  key={item.ip}
                  className={`rounded-full border px-3 py-1 text-xs ${i === index ? "border-[#9a3412] bg-[#9a3412] text-white" : "bg-white"}`}
                  onClick={() => setIndex(i)}
                >
                  {item.kind === "tailscale" ? "Tailscale" : "局域网"} {item.base}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-1 rounded-xl bg-[#efe8dc] p-1 text-xs">
              <button data-testid="qr-app" className={`rounded-lg py-1.5 ${kind === "app" ? "bg-white shadow-sm" : ""}`} onClick={() => setKind("app")}>安卓 App 扫码</button>
              <button data-testid="qr-web" className={`rounded-lg py-1.5 ${kind === "web" ? "bg-white shadow-sm" : ""}`} onClick={() => setKind("web")}>iPhone / 浏览器扫码</button>
            </div>
            <div className="relative mx-auto size-56 overflow-hidden rounded-xl border bg-white p-2">
              <div
                data-testid="mobile-qr"
                data-revealed={reveal ? "1" : "0"}
                className={`size-full transition [&>svg]:size-full ${reveal ? "" : "blur-md"}`}
                dangerouslySetInnerHTML={{ __html: svg }}
              />
              {!reveal && (
                <button data-testid="reveal-qr" className="absolute inset-0 grid place-items-center bg-white/40 text-sm font-medium" onClick={() => setReveal(true)}>
                  点一下显示二维码
                </button>
              )}
            </div>
            <p className="text-xs text-[#6b6258]">
              {kind === "app"
                ? "用 ChatCluster 安卓 App 扫码，会自动连接并记住这台电脑。"
                : "用手机相机或浏览器扫码，打开后点 Safari「分享 → 添加到主屏幕」/ Chrome「添加到主屏幕」即可像 App 一样使用。"}
            </p>
            {addr?.web_link && (
              <div className="flex items-center gap-2 rounded-lg border bg-white px-2 py-1.5">
                <code data-testid="pair-link" className="min-w-0 flex-1 truncate text-xs">{maskLink(addr.web_link)}</code>
                <Button size="xs" variant="outline" onClick={() => void copy()}>复制链接</Button>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" data-testid="rotate-token" onClick={() => void rotate()}>更换口令</Button>
              {reveal && <Button size="sm" variant="ghost" onClick={() => setReveal(false)}>隐藏二维码</Button>}
            </div>
            {note && <p data-testid="mobile-note" className="text-xs text-[#9a3412]">{note}</p>}
            <p className="rounded-lg bg-[#fff1df] px-3 py-2 text-xs text-[#9a3412]">
              二维码和配对链接等同于钥匙：不要截图分享、不要发到群里。只在自己家的 Wi-Fi 或 Tailscale 里用，不要做端口转发或暴露到公网。手机丢了或怀疑泄露，点「更换口令」。
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
