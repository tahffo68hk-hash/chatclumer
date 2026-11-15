// 命令行管理手机配对口令：node server/mobile-token.mjs status|rotate
// 不会打印完整口令。完整口令只在电脑本机的「手机连接」面板里显示。
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TokenStore, mask } from "./mobile-auth.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const dataDir = process.env.CC_DATA_DIR || path.join(root, "backend", "data");
const store = new TokenStore(path.join(dataDir, "mobile_token.json"));
const cmd = process.argv[2] || "status";
if (cmd === "rotate") {
  const t = store.rotate();
  console.log(`已更换手机配对口令（${mask(t)}）。之前配对的手机都需要重新扫码。`);
} else if (cmd === "status") {
  const t = store.read();
  console.log(t ? `已有手机配对口令（${mask(t)}）。` : "还没有手机配对口令。用 LAN=1 启动时会自动生成。");
} else {
  console.error("用法：node server/mobile-token.mjs status|rotate");
  process.exit(2);
}
