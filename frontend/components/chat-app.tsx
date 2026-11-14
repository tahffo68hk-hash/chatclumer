"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Plus, Square } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { RichText } from "@/components/rich-text";
import { api, eventUrl } from "@/lib/api";
import type { CatalogItem, ChatMessage, HighlightCard, Member, RoomGroup, Session, SplitItem } from "@/lib/types";

const MODES = [
  { id: "free_chat", label: "自由群聊" },
  { id: "independent", label: "独立回答" },
  { id: "debate", label: "交叉辩论" },
  { id: "summary", label: "只总结" },
] as const;

function clock(iso?: string | null) {
  if (!iso) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(new Date(iso));
}

function downloadRoom(kind: "md" | "json", sessionId: string | null, messages: ChatMessage[], cards: HighlightCard[]) {
  const rows = messages.map((message) => ({
    time: message.created_at,
    nickname: message.nickname,
    role: message.role_name,
    content: message.content,
    status: message.status,
    model: shownModel(message),
  }));
  const saved = cards.map((card) => ({
    title: card.title,
    note: card.note,
    nickname: card.nickname,
    excerpt: card.excerpt,
    disclaimer: card.disclaimer,
  }));
  const body = kind === "json"
    ? JSON.stringify({ messages: rows, highlights: saved, disclaimer: "收藏的是讨论里的原话和备注，不是已核实事实。" }, null, 2)
    : `${rows.map((row) => `## ${row.nickname || "房间"} · ${row.time}\n\n${row.content}`).join("\n\n")}\n\n# 收藏\n\n收藏的是讨论里的原话和备注，不是已核实事实。\n\n${saved.map((card) => `## ${card.title}\n\n${card.nickname}：${card.excerpt}\n\n备注：${card.note || "无"}`).join("\n\n")}`;
  const blob = new Blob([body], { type: kind === "json" ? "application/json" : "text/markdown" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `room-${sessionId || "chat"}.${kind === "json" ? "json" : "md"}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function shownModel(message: ChatMessage) {
  const id = message.model_id || "";
  if (!id || id.startsWith("web:") || id.includes("未能核验")) return "未能核验精确 model ID";
  return id;
}

function applyTheme(mode: "light" | "dark" | "system") {
  localStorage.setItem("room-theme", mode);
  const dark = mode === "dark" || (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

function applyText(size: string) {
  localStorage.setItem("room-text", size);
  document.documentElement.dataset.text = size;
}

function upsert(list: ChatMessage[], message: ChatMessage) {
  const index = list.findIndex((item) => item.id === message.id);
  if (index < 0) return [...list, message];
  const next = list.slice();
  next[index] = message;
  return next;
}

function phaseLabel(phase?: string | null) {
  if (phase === "independent") return "独立回答";
  if (phase === "cross") return "接话";
  if (phase === "summary") return "总结";
  return "";
}

const WEB_SITES = [
  { id: "fixture", label: "本地夹具", origin: "http://127.0.0.1:43124/fixture/chat" },
  { id: "gemini", label: "Gemini", origin: "https://gemini.google.com/app" },
  { id: "yuanbao", label: "腾讯元宝", origin: "https://yuanbao.tencent.com/chat/" },
  { id: "zhipu", label: "智谱清言 chatglm.cn", origin: "https://chatglm.cn/" },
  { id: "doubao", label: "豆包", origin: "https://www.doubao.com/chat/" },
  { id: "qwen", label: "Qwen", origin: "https://chat.qwen.ai/" },
  { id: "deepseek", label: "DeepSeek", origin: "https://chat.deepseek.com/" },
  { id: "chatgpt", label: "ChatGPT", origin: "https://chatgpt.com/" },
  { id: "claude", label: "Claude", origin: "https://claude.ai/" },
  { id: "grok", label: "Grok", origin: "https://grok.com/" },
];

function freshTabKey(site: string) {
  return `${site}-${Math.random().toString(36).slice(2, 8)}`;
}

function bindStatus(member: Member) {
  if (member.provider !== "web") return "";
  return member.web_link || "未绑定";
}

const emptyMember = {
  nickname: "",
  role_name: "",
  persona: "",
  provider: "demo",
  model_id: "demo-synthesizer-v1",
  api_base: "",
  api_key_env: "",
  enabled: true,
  web_site: "fixture",
  web_origin: WEB_SITES[0].origin,
  web_tab_key: "",
  web_auto: false,
};

export function ChatApp() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [groups, setGroups] = useState<RoomGroup[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [preview, setPreview] = useState("");
  const [audience, setAudience] = useState("all");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark" | "system">("system");
  const [textSize, setTextSize] = useState("normal");
  const [link, setLink] = useState<"ok" | "down">("ok");
  const [pairCode, setPairCode] = useState("");
  const [webMemory, setWebMemory] = useState<"rebind" | "retain">("rebind");
  const [highlights, setHighlights] = useState<HighlightCard[]>([]);
  const [cardsOpen, setCardsOpen] = useState(false);
  const [splitsOpen, setSplitsOpen] = useState(false);
  const [splits, setSplits] = useState<{ items: SplitItem[]; notice: string } | null>(null);
  const [favFor, setFavFor] = useState<string | null>(null);
  const [favTitle, setFavTitle] = useState("");
  const [favNote, setFavNote] = useState("");
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pane, setPane] = useState<"chat" | "people" | "run">("chat");
  const [sideTab, setSideTab] = useState<"rooms" | "members" | "records">("rooms");
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  const [memberOpen, setMemberOpen] = useState(false);
  const [memberError, setMemberError] = useState("");
  const [connectOpen, setConnectOpen] = useState(false);
  const [memberForm, setMemberForm] = useState(emptyMember);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [secretOpen, setSecretOpen] = useState(false);
  const [secretName, setSecretName] = useState("OPENAI_API_KEY");
  const [secretValue, setSecretValue] = useState("");
  const [secretState, setSecretState] = useState<{ name: string; configured: boolean }[]>([]);
  const [allowPaid, setAllowPaid] = useState(false);
  const [integration, setIntegration] = useState("");
  const [now, setNow] = useState(Date.now());
  const [settings, setSettings] = useState({
    max_rounds: 3,
    max_ai_messages: 10,
    max_seconds: 120,
    max_tokens: "",
    max_cost_usd: "",
    cross_delay_ms: 120,
    room_rule: "",
    summary_mode: "local",
    summary_member_id: "",
    summary_provider: "openai",
    summary_model_id: "",
    stop_on_no_new_point: true,
  });
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const loadList = useCallback(async () => {
    const rows = await api.sessions();
    setSessions(rows);
    return rows;
  }, []);

  const loadRoom = useCallback(async (id: string) => {
    const [detail, msgs, saved] = await Promise.all([api.session(id), api.messages(id), api.highlights(id)]);
    setSession(detail.session);
    setMembers(detail.members);
    setGroups(detail.groups || []);
    setMessages(msgs);
    setHighlights(saved.cards);
    setSettings({
      max_rounds: detail.session.max_rounds,
      max_ai_messages: detail.session.max_ai_messages,
      max_seconds: detail.session.max_seconds,
      max_tokens: detail.session.max_tokens ? String(detail.session.max_tokens) : "",
      max_cost_usd: detail.session.max_cost_usd != null ? String(detail.session.max_cost_usd) : "",
      cross_delay_ms: detail.session.cross_delay_ms,
      room_rule: detail.session.room_rule || "",
      summary_mode: detail.session.summary_mode,
      summary_member_id: detail.session.summary_member_id || "",
      summary_provider: detail.session.summary_provider || "openai",
      summary_model_id: detail.session.summary_model_id || "",
      stop_on_no_new_point: detail.session.stop_on_no_new_point,
    });
  }, []);

  useEffect(() => {
    let stop = false;
    (async () => {
      try {
        await api.health();
        const [rows, cat, secrets, integ] = await Promise.all([api.sessions(), api.catalog(), api.secrets(), api.integrations()]);
        if (stop) return;
        setSessions(rows);
        setCatalog(cat.providers);
        setSecretState(secrets.secrets);
        setAllowPaid(secrets.allow_paid);
        setIntegration(`${integ.qq.state} / ${integ.wechat.state}`);
        if (rows[0]) setCurrentId(rows[0].id);
      } catch (err) {
        if (!stop) setError(err instanceof Error ? err.message : "后端没有响应");
      } finally {
        if (!stop) setLoading(false);
      }
    })();
    return () => {
      stop = true;
    };
  }, []);

  useEffect(() => {
    if (!currentId) return;
    loadRoom(currentId).catch((err) => setError(err.message));
  }, [currentId, loadRoom]);

  useEffect(() => {
    if (!currentId) return;
    const source = new EventSource(eventUrl(currentId));
    source.addEventListener("snapshot", (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      setSession(data.session);
      setMembers(data.members);
      setMessages(data.messages);
    });
    source.addEventListener("session", (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      setSession(data);
      setSessions((rows) => rows.map((row) => (row.id === data.id ? { ...row, ...data } : row)));
    });
    source.addEventListener("message", (event) => {
      const data = JSON.parse((event as MessageEvent).data) as ChatMessage;
      setMessages((list) => upsert(list, data));
    });
    source.onerror = () => {
      setLink("down");
      source.close();
    };
    return () => source.close();
  }, [currentId]);

  useEffect(() => {
    if (!currentId) return;
    const timer = window.setInterval(() => {
      if (!session || session.status === "running" || session.status === "paused") {
        loadRoom(currentId).catch(() => undefined);
        loadList().catch(() => undefined);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [currentId, loadList, loadRoom, session]);

  useEffect(() => {
    const storedTheme = localStorage.getItem("room-theme");
    const storedText = localStorage.getItem("room-text");
    if (storedTheme === "light" || storedTheme === "dark" || storedTheme === "system") setTheme(storedTheme);
    if (storedText) setTextSize(storedText);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (stickRef.current) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, session?.status]);

  const byId = useMemo(() => new Map(messages.map((item) => [item.id, item])), [messages]);
  const demoRoom = members.some((item) => item.enabled && item.provider === "demo");
  const busy = session?.status === "running" || session?.status === "paused";
  const remain = session?.deadline_at && session.status === "running"
    ? Math.max(0, Math.ceil((new Date(session.deadline_at).getTime() - now) / 1000))
    : null;

  async function createDemo() {
    setError("");
    const created = await api.createSession({ title: "未命名群聊", template: "demo", mode: "free_chat" });
    await loadList();
    setCurrentId(created.id);
    setPane("chat");
  }

  async function createBranches() {
    setError("");
    const created = await api.createSession({ title: "独立分支", template: "demo", mode: "free_chat", layout: "branches" });
    await loadList();
    setCurrentId(created.id);
    setPane("chat");
  }

  async function createBlank() {
    const created = await api.createSession({ title: "空白房间", template: null, mode: "free_chat" });
    await loadList();
    setCurrentId(created.id);
    setSideTab("members");
    setPane("people");
  }

  async function send(content: string, replyId?: string) {
    if (!currentId || !content.trim()) return;
    setError("");
    try {
      const groupId = audience.startsWith("group:") ? audience.slice(6) : undefined;
      await api.send(currentId, content.trim(), replyId, session?.mode, session?.layout === "branches" ? (groupId ? "group" : "all") : undefined, groupId);
      setReplyTo(null);
      stickRef.current = true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
      throw err;
    }
  }

  async function control(action: "pause" | "resume" | "stop") {
    if (!currentId) return;
    setError("");
    try {
      if (action === "pause") await api.pause(currentId);
      if (action === "resume") await api.resume(currentId);
      if (action === "stop") await api.stop(currentId);
      await loadRoom(currentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function saveSettings() {
    if (!currentId) return;
    setError("");
    try {
      await api.patchSession(currentId, {
        mode: session?.mode,
        max_rounds: Number(settings.max_rounds),
        max_ai_messages: Number(settings.max_ai_messages),
        max_seconds: Number(settings.max_seconds),
        max_tokens: settings.max_tokens ? Number(settings.max_tokens) : null,
        max_cost_usd: settings.max_cost_usd ? Number(settings.max_cost_usd) : null,
        clear_token_cap: !settings.max_tokens,
        clear_cost_cap: !settings.max_cost_usd,
        cross_delay_ms: Number(settings.cross_delay_ms),
        room_rule: settings.room_rule,
        summary_mode: settings.summary_mode,
        summary_member_id: settings.summary_mode === "member" ? settings.summary_member_id || null : null,
        summary_provider: settings.summary_mode === "provider" ? settings.summary_provider : null,
        summary_model_id: settings.summary_mode === "provider" ? settings.summary_model_id.trim() : null,
        stop_on_no_new_point: settings.stop_on_no_new_point,
      });
      await loadRoom(currentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    }
  }

  function openCreateMember() {
    const preset = catalog.find((item) => item.provider === "demo");
    setEditingId(null);
    setMemberError("");
    setMemberForm({ ...emptyMember, model_id: preset?.model_id || "demo-synthesizer-v1" });
    setMemberOpen(true);
  }

  function openEditMember(member: Member) {
    setEditingId(member.id);
    setMemberError("");
    setMemberForm({
      nickname: member.nickname,
      role_name: member.role_name,
      persona: member.persona,
      provider: member.provider,
      model_id: member.model_id,
      api_base: member.api_base || "",
      api_key_env: member.api_key_env || "",
      enabled: member.enabled,
      web_site: member.web_site || "fixture",
      web_origin: member.web_origin || WEB_SITES.find((item) => item.id === (member.web_site || "fixture"))?.origin || "",
      web_tab_key: member.web_tab_key || "",
      web_auto: Boolean(member.web_auto),
    });
    setMemberOpen(true);
  }

  async function saveMember() {
    if (!currentId) return;
    setMemberError("");
    if (memberForm.provider === "web" && (!memberForm.web_origin.trim() || !memberForm.web_tab_key.trim())) {
      setMemberError("网页会话要填写页面地址和绑定键");
      return;
    }
    const body = {
      nickname: memberForm.nickname,
      role_name: memberForm.role_name,
      persona: memberForm.persona,
      provider: memberForm.provider,
      model_id: memberForm.model_id,
      api_base: memberForm.api_base || null,
      api_key_env: memberForm.api_key_env || null,
      enabled: memberForm.enabled,
    };
    try {
      if (memberForm.provider === "web" && !editingId) {
        await api.addWebMember(currentId, {
          ...body,
          web_site: memberForm.web_site,
          web_origin: memberForm.web_origin.trim(),
          web_tab_key: memberForm.web_tab_key.trim(),
          web_auto: memberForm.web_auto,
        });
      } else {
        const saved = editingId ? await api.patchMember(editingId, body) : await api.addMember(currentId, body);
        if (memberForm.provider === "web") {
          try {
            await api.webBind(saved.id, {
              web_site: memberForm.web_site,
              web_origin: memberForm.web_origin.trim(),
              web_tab_key: memberForm.web_tab_key.trim(),
              web_auto: memberForm.web_auto,
            });
          } catch (err) {
            if (!editingId) await api.deleteMember(saved.id).catch(() => undefined);
            throw err;
          }
        }
      }
      setMemberOpen(false);
      await loadRoom(currentId);
    } catch (err) {
      setMemberError(err instanceof Error ? err.message : "成员保存失败");
    }
  }

  async function toggleMember(member: Member, enabled: boolean) {
    await api.patchMember(member.id, { ...member, api_base: member.api_base || null, api_key_env: member.api_key_env || null, enabled });
    if (currentId) await loadRoom(currentId);
  }

  async function removeMember(member: Member) {
    await api.deleteMember(member.id);
    if (currentId) await loadRoom(currentId);
  }

  async function saveSecret() {
    await api.saveSecret(secretName, secretValue);
    setSecretValue("");
    const status = await api.secrets();
    setSecretState(status.secrets);
    setAllowPaid(status.allow_paid);
  }

  const mode = session?.mode || "free_chat";

  return (
    <div className="room-app flex h-dvh flex-col bg-[#efe8dc] text-[#1c1915]">
      <div className="grid min-h-0 flex-1 lg:grid-cols-[280px_minmax(0,1fr)_320px]">
        <aside className={`${pane === "people" ? "flex" : "hidden"} min-h-0 flex-col bg-[#1b1916] text-[#f6f1e8] lg:flex`}>
          <div className="flex items-center justify-between px-4 py-4">
            <div>
              <p className="text-[11px] tracking-[0.18em] text-[#c8b8a2]">MULTI-LLM ROOM</p>
              <h1 className="serif text-xl">多模型群聊</h1>
            </div>
          </div>
          <div className="mx-3 grid grid-cols-3 gap-1 rounded-xl bg-white/5 p-1 text-xs">
            {(
              [
                ["rooms", "会话"],
                ["members", "成员"],
                ["records", "记录"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                className={`rounded-lg px-2 py-1.5 ${sideTab === id ? "bg-[#fff7ed] text-[#1c1915]" : "text-[#d9cbb8]"}`}
                onClick={() => setSideTab(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex gap-2 px-3 py-3">
            <Button data-testid="create-demo" size="sm" onClick={createDemo}>
              演示群
            </Button>
            <Button data-testid="create-branches" size="sm" variant="secondary" onClick={createBranches}>
              独立分支
            </Button>
            <Button size="sm" variant="secondary" onClick={createBlank}>
              空白群
            </Button>
          </div>
          <ScrollArea className="min-h-0 flex-1 px-3 pb-4">
            {sideTab !== "members" &&
              sessions.map((item) => (
                <button
                  key={item.id}
                  data-testid="session-item"
                  className={`mb-2 w-full rounded-xl px-3 py-3 text-left ${item.id === currentId ? "bg-white/10" : "hover:bg-white/5"}`}
                  onClick={() => {
                    setCurrentId(item.id);
                    setPane("chat");
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{item.title}</span>
                    <span className="text-[11px] text-[#d9cbb8]">{item.status_label}</span>
                  </div>
                  <p className="mt-1 text-xs text-[#b7a894]">
                    {sideTab === "records"
                      ? `${item.end_reason_label || "未结束"} · ${item.message_count || 0} 条`
                      : `${item.member_count || 0} 位成员 · ${clock(item.updated_at)}`}
                  </p>
                </button>
              ))}
            {sideTab === "members" && (
              <div className="space-y-2">
                {members.map((member) => (
                  <div key={member.id} className="rounded-xl bg-white/5 p-3">
                    <div className="flex items-center gap-2">
                      <span className="grid size-8 place-items-center rounded-full text-sm text-white" style={{ background: member.avatar_color }}>
                        {member.nickname.slice(0, 1)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm">{member.nickname}</p>
                        <p className="truncate text-[11px] text-[#d9cbb8]">{member.role_name}</p>
                      </div>
                      <Switch checked={member.enabled} onCheckedChange={(value) => toggleMember(member, value)} />
                    </div>
                    <p className="mt-2 truncate font-mono text-[11px] text-[#e7d7c4]">
                      {member.provider} · {member.model_id}
                    </p>
                    {member.provider === "web" && (
                      <div className="mt-2 space-y-1 text-[11px] text-[#e7d7c4]" data-testid="web-card">
                        <p data-testid="bind-status">{bindStatus(member)}</p>
                        <label className="block">成员 ID
                          <input readOnly data-testid="member-id" className="mt-1 w-full rounded bg-black/20 px-2 py-1 font-mono" value={member.id} />
                        </label>
                        <label className="block">绑定键
                          <input readOnly data-testid="tab-key" className="mt-1 w-full rounded bg-black/20 px-2 py-1 font-mono" value={member.web_tab_key || ""} />
                        </label>
                      </div>
                    )}
                    <div className="mt-2 flex gap-2">
                      <Button size="xs" variant="secondary" onClick={() => openEditMember(member)}>
                        编辑
                      </Button>
                      <Button size="xs" variant="ghost" className="text-[#f6f1e8]" onClick={() => removeMember(member)}>
                        移除
                      </Button>
                    </div>
                  </div>
                ))}
                <Button data-testid="add-member" variant="secondary" className="w-full" onClick={openCreateMember}>
                  <Plus /> 添加成员
                </Button>
                <Button data-testid="connect-web-help" variant="ghost" className="w-full text-[#f6f1e8]" onClick={() => setConnectOpen(true)}>
                  连接网页 AI
                </Button>
              </div>
            )}
            {sideTab !== "members" && sessions.length === 0 && <p className="px-2 text-sm text-[#d9cbb8]">还没有房间。</p>}
          </ScrollArea>
        </aside>

        <main className={`${pane === "chat" ? "flex" : "hidden"} min-h-0 min-w-0 flex-col lg:flex`}>
          <header className="border-b border-[#e4d8c8] bg-[#f7f3eb] px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="serif text-2xl">{session?.title || "选择一个房间"}</h2>
              <Button data-testid="open-settings" size="sm" variant="outline" onClick={() => setSettingsOpen(true)}>设置</Button>
              <Button data-testid="open-cards" size="sm" variant="outline" disabled={!currentId} onClick={() => setCardsOpen(true)}>收藏</Button>
              <Button data-testid="open-splits" size="sm" variant="outline" disabled={!currentId} onClick={() => {
                if (!currentId) return;
                void api.disagreements(currentId).then((payload) => {
                  setSplits(payload);
                  setSplitsOpen(true);
                }).catch((err) => setError(err.message));
              }}>分歧</Button>
              {session && (
                <Badge data-testid="status-pill" variant={session.status === "running" ? "default" : "secondary"}>
                  {session.status_label}
                </Badge>
              )}
              {session && session.current_round > 0 && <Badge variant="outline">第 {session.current_round} 轮</Badge>}
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[#6b6258]">
              {session?.speaking_nicknames?.length ? (
                <span data-testid="speaking">{session.speaking_nicknames.join("、")} 正在说</span>
              ) : (
                <span>{busy ? "等待下一位" : "时间线安静"}</span>
              )}
              {session?.end_reason_label && (
                <span data-testid="end-reason">结束原因：{session.end_reason_label}</span>
              )}
            </div>
            {session?.layout === "branches" && (
              <div data-testid="branch-bar" className="mt-3 space-y-2 rounded-lg border border-[#e4d8c8] bg-white p-3 text-sm">
                <p>同一问题先各自分支。勾选至少两人后，先预览将共享的公开答复，再合并。未勾选的历史不会默认传走。发到网页的内容会离开这台电脑，网页不显示单价时费用记为未知。</p>
                <div className="flex flex-wrap gap-2">
                  {members.map((member) => (
                    <label key={member.id} className="flex items-center gap-1 rounded-full border px-2 py-1">
                      <input
                        data-testid={`pick-${member.nickname}`}
                        type="checkbox"
                        checked={picked.includes(member.id)}
                        onChange={(event) => {
                          setPicked((current) => event.target.checked ? [...current, member.id] : current.filter((id) => id !== member.id));
                        }}
                      />
                      {member.nickname}
                      <span className="text-[11px] text-[#6b6258]">{groups.find((group) => group.status === "active" && group.member_ids.includes(member.id))?.name}</span>
                    </label>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" data-testid="preview-merge" onClick={() => void api.previewMerge(currentId || "", picked).then((plan) => setPreview(`${plan.note}\n${plan.shares.map((item) => `${item.nickname}：${item.excerpt}`).join("\n")}`)).catch((err) => setError(err.message))}>预览将共享的内容</Button>
                  <Button size="sm" data-testid="confirm-merge" onClick={() => void api.merge(currentId || "", picked).then(() => { if (currentId) return loadRoom(currentId); }).catch((err) => setError(err.message))}>合并为讨论组</Button>
                  <Button size="sm" variant="outline" data-testid="split-fresh" onClick={() => {
                    const group = groups.find((item) => item.status === "active" && item.kind === "discussion" && picked.some((id) => item.member_ids.includes(id)));
                    if (!currentId || !group) {
                      setError("先选中讨论组里要拆出去的成员");
                      return;
                    }
                    void api.split(currentId, group.id, picked.filter((id) => group.member_ids.includes(id)), "fresh", webMemory).then(() => loadRoom(currentId)).catch((err) => setError(err.message));
                  }}>拆成新分支</Button>
                </div>
                <label className="text-xs text-[#6b6258]">拆出后的网页
                  <select data-testid="web-memory" className="ml-2 rounded border bg-white px-2 py-1" value={webMemory} onChange={(event) => setWebMemory(event.target.value as "rebind" | "retain")}>
                    <option value="rebind">绑定新的独立会话后再发送</option>
                    <option value="retain">沿用已有记忆</option>
                  </select>
                </label>
                {preview && <p data-testid="merge-preview" className="whitespace-pre-wrap text-xs text-[#6b6258]">{preview}</p>}
              </div>
            )}
            {demoRoom && (
              <p data-testid="demo-banner" className="mt-2 rounded-lg bg-[#fff1df] px-3 py-2 text-sm text-[#9a3412]">
                演示模式：带「非真实模型」标记的话是合成回复，不是 GPT、Claude、Gemini 或 Grok 的输出。
              </p>
            )}
          </header>
          {error && <p className="bg-[#fee4e2] px-4 py-2 text-sm text-[#b42318]">{error}</p>}
          <div
            className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6"
            onScroll={(event) => {
              const node = event.currentTarget;
              stickRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
            }}
          >
            {loading && (
              <p className="flex items-center gap-2 text-sm text-[#6b6258]">
                <Loader2 className="size-4 animate-spin" /> 正在读取房间
              </p>
            )}
            {!loading && !session && (
              <div className="mx-auto mt-16 max-w-md text-center">
                <h3 className="serif text-3xl">还没有讨论</h3>
                <p className="mt-3 text-sm leading-6 text-[#6b6258]">
                  建一个演示群，三个角色共用同一个 demo 模型。他们会先各自回答，再在这一条时间线里引用对方。
                </p>
                <Button className="mt-5" data-testid="create-demo-main" onClick={createDemo}>
                  创建演示群
                </Button>
              </div>
            )}
            {link === "down" && (
              <p data-testid="link-down" className="mx-auto mb-3 max-w-3xl rounded-lg bg-[#fff1df] px-3 py-2 text-sm text-[#9a3412]">
                和本机后端的连接断了。重新读取不会再次发送上一条。
                <Button className="ml-2" size="sm" variant="outline" data-testid="reload-room" onClick={() => currentId && loadRoom(currentId).then(() => setLink("ok")).catch((err) => setError(err.message))}>重新读取</Button>
              </p>
            )}
            {error && /登录|验证/.test(error) && (
              <p data-testid="login-wait" className="mx-auto mb-3 max-w-3xl rounded-lg bg-[#fff1df] px-3 py-2 text-sm text-[#9a3412]">网页停在登录或验证。这一站不再自动发送。</p>
            )}
            {session && messages.length === 0 && (
              <p className="mx-auto mt-10 max-w-lg text-center text-sm leading-6 text-[#6b6258]">
                写下一句。启用的成员会先独立回答，彼此看不到这一轮正在生成的内容；之后才能引用公开发言。
              </p>
            )}
            <div className="mx-auto flex max-w-3xl flex-col gap-3">
              {messages.map((message) => (
                <MessageRow
                  key={message.id}
                  message={message}
                  reply={message.reply_to_id ? byId.get(message.reply_to_id) : undefined}
                  onReply={() => setReplyTo(message)}
                  onFavorite={() => {
                    const existing = highlights.find((card) => card.message_id === message.id);
                    setFavFor(message.id);
                    setFavTitle(existing?.title || "");
                    setFavNote(existing?.note || "");
                  }}
                />
              ))}
              <div ref={bottomRef} />
            </div>
          </div>
          <Composer
            busy={!!busy}
            disabled={!currentId}
            members={members}
            groups={groups}
            audience={audience}
            onAudience={setAudience}
            reply={replyTo}
            onClearReply={() => setReplyTo(null)}
            onSend={send}
          />
        </main>

        <aside className={`${pane === "run" ? "flex" : "hidden"} min-h-0 flex-col border-[#e4d8c8] bg-[#f7f3eb] lg:flex lg:border-l`}>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-4 p-4">
              <section>
                <p className="text-xs tracking-wide text-[#6b6258]">讨论方式</p>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {MODES.map((item) => (
                    <Button
                      key={item.id}
                      size="sm"
                      variant={mode === item.id ? "default" : "outline"}
                      onClick={() => currentId && api.patchSession(currentId, { mode: item.id }).then(() => loadRoom(currentId)).catch((err) => setError(err.message))}
                    >
                      {item.label}
                    </Button>
                  ))}
                </div>
              </section>
              <section className="grid grid-cols-2 gap-2 text-sm">
                <Meter label="轮次" value={`${session?.current_round || 0}/${session?.max_rounds || settings.max_rounds}`} />
                <Meter label="AI 消息" value={`${session?.ai_message_count || 0}/${session?.max_ai_messages || settings.max_ai_messages}`} />
                <Meter label="剩余秒" value={remain == null ? "—" : String(remain)} />
                <Meter label="token" value={session?.run_tokens_known === false ? "未知" : String(session?.run_tokens || 0)} />
                <Meter label="费用 USD" value={session?.run_cost_known === false ? "未知" : (session?.run_cost_usd || 0).toFixed(4)} />
                <Meter label="上下文版本" value={String(session?.context_version || 0)} />
              </section>
              <section className="flex flex-wrap gap-2">
                <Button data-testid="pause-button" variant="outline" disabled={session?.status !== "running"} onClick={() => control("pause")}>
                  暂停
                </Button>
                <Button data-testid="resume-button" variant="outline" disabled={session?.status !== "paused"} onClick={() => control("resume")}>
                  继续
                </Button>
                <Button data-testid="stop-button" variant="destructive" disabled={!busy} onClick={() => control("stop")}>
                  <Square /> 停止
                </Button>
              </section>
              <section className="space-y-2">
                <p className="text-xs text-[#6b6258]">硬上限。运行中不能改，到点就不再发请求。</p>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="轮数" value={settings.max_rounds} onChange={(value) => setSettings({ ...settings, max_rounds: Number(value) })} disabled={!!busy} />
                  <Field label="AI 消息" value={settings.max_ai_messages} onChange={(value) => setSettings({ ...settings, max_ai_messages: Number(value) })} disabled={!!busy} />
                  <Field label="秒" value={settings.max_seconds} onChange={(value) => setSettings({ ...settings, max_seconds: Number(value) })} disabled={!!busy} />
                  <Field label="间隔 ms" value={settings.cross_delay_ms} onChange={(value) => setSettings({ ...settings, cross_delay_ms: Number(value) })} disabled={!!busy} />
                  <Field label="token 上限" value={settings.max_tokens} onChange={(value) => setSettings({ ...settings, max_tokens: value })} disabled={!!busy} />
                  <Field label="费用上限" value={settings.max_cost_usd} onChange={(value) => setSettings({ ...settings, max_cost_usd: value })} disabled={!!busy} />
                </div>
                <Label className="text-xs">房间规则</Label>
                <Textarea value={settings.room_rule} disabled={!!busy} onChange={(event) => setSettings({ ...settings, room_rule: event.target.value })} />
                <div className="flex items-center justify-between text-sm">
                  <span>无新观点可早停</span>
                  <Switch checked={settings.stop_on_no_new_point} disabled={!!busy} onCheckedChange={(value) => setSettings({ ...settings, stop_on_no_new_point: value })} />
                </div>
                <Label className="text-xs">总结</Label>
                <select
                  className="h-9 w-full rounded-lg border bg-white px-2 text-sm"
                  disabled={!!busy}
                  value={settings.summary_mode === "member" ? settings.summary_member_id : settings.summary_mode}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value === "local") setSettings({ ...settings, summary_mode: "local", summary_member_id: "" });
                    else if (value === "provider") setSettings({ ...settings, summary_mode: "provider", summary_member_id: "" });
                    else setSettings({ ...settings, summary_mode: "member", summary_member_id: value });
                  }}
                >
                  <option value="local">本地回顾，不额外请求模型</option>
                  <option value="provider">指定总结模型（占用 1 条额度）</option>
                  {members.map((member) => (
                    <option key={member.id} value={member.id}>
                      由 {member.nickname} 总结（占用 1 条额度）
                    </option>
                  ))}
                </select>
                {settings.summary_mode === "provider" && (
                  <div className="grid gap-2">
                    <select
                      data-testid="summary-provider"
                      className="h-9 w-full rounded-lg border bg-white px-2 text-sm"
                      disabled={!!busy}
                      value={settings.summary_provider}
                      onChange={(event) => setSettings({ ...settings, summary_provider: event.target.value })}
                    >
                      {catalog.map((item) => (
                        <option key={item.provider} value={item.provider}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                    <Input
                      data-testid="summary-model"
                      disabled={!!busy}
                      value={settings.summary_model_id}
                      placeholder="精确 model ID"
                      onChange={(event) => setSettings({ ...settings, summary_model_id: event.target.value })}
                    />
                    <p className="text-[11px] leading-5 text-[#6b6258]">
                      有密钥且额度和时间还够时，才请求这个模型写六段综合。无密钥、已停止或预算不够时，仍标明本地回顾，不会伪装成该模型。
                    </p>
                  </div>
                )}
                <Button data-testid="save-limits" variant="secondary" disabled={!!busy} onClick={() => void saveSettings()}>
                  保存上限
                </Button>
              </section>
              <section>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-xs text-[#6b6258]">在场成员</p>
                  <Button size="xs" variant="outline" onClick={() => setSecretOpen(true)}>
                    密钥
                  </Button>
                </div>
                <div className="space-y-2">
                  {members.map((member) => {
                    const speaking = session?.speaking_member_ids?.includes(member.id);
                    return (
                      <div key={member.id} className="rounded-xl border bg-white p-3">
                        <div className="flex items-center gap-2">
                          <span className="grid size-9 place-items-center rounded-full text-sm text-white" style={{ background: member.avatar_color }}>
                            {member.nickname.slice(0, 1)}
                          </span>
                          <div className="min-w-0">
                            <p className="text-sm font-medium">
                              {member.nickname} <span className="font-normal text-[#6b6258]">{member.role_name}</span>
                            </p>
                            <p className="truncate font-mono text-[11px] text-[#6b6258]">
                              {member.provider} / {member.model_id}
                            </p>
                          </div>
                        </div>
                        <p className="mt-2 text-xs text-[#6b6258]">
                          {speaking ? "正在说" : member.enabled ? "启用" : "已禁用"}
                          {member.provider !== "demo" ? " · 无密钥则跳过，不伪装" : " · 合成演示"}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </section>
              <p className="text-[11px] leading-5 text-[#6b6258]">
                外部渠道 {integration || "读取中"}。QQ 与微信默认 BLOCKED_EXTERNAL，网页房间不依赖它们。默认只监听本机。
              </p>
            </div>
          </ScrollArea>
        </aside>
      </div>

      <nav className="grid grid-cols-3 border-t border-[#e4d8c8] bg-[#f7f3eb] p-2 lg:hidden">
        {(
          [
            ["people", "会话"],
            ["chat", "聊天"],
            ["run", "现场"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} data-testid={`nav-${id}`} className={`rounded-lg py-2 text-sm ${pane === id ? "bg-[#9a3412] text-white" : ""}`} onClick={() => setPane(id)}>
            {label}
          </button>
        ))}
      </nav>

      <Dialog open={cardsOpen} onOpenChange={setCardsOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>收藏</DialogTitle>
            <DialogDescription>这些卡片只保留原话和你的备注。它们不是已核实事实。</DialogDescription>
          </DialogHeader>
          {highlights.length === 0 && <p data-testid="cards-empty">还没有收藏。</p>}
          <div className="grid gap-3">
            {highlights.map((card) => (
              <article key={card.id} data-testid="highlight-card" className="rounded-xl border p-3 text-sm">
                <p className="font-medium">{card.title}</p>
                <p className="mt-1 text-xs text-[#6b6258]">{card.nickname || "房间"} · 讨论观点</p>
                <p className="mt-2">{card.excerpt}</p>
                {card.note && <p className="mt-1 text-[#6b6258]">备注：{card.note}</p>}
                <p className="mt-2 text-xs text-[#9a3412]">{card.disclaimer}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" data-testid="jump-card" onClick={() => jumpTo(card.message_id)}>回到原消息</Button>
                  <Button size="sm" variant="outline" onClick={() => void navigator.clipboard.writeText(`${card.title}\n${card.nickname}：${card.excerpt}\n${card.note}\n${card.disclaimer}`)}>复制</Button>
                  <Button size="sm" variant="ghost" onClick={() => currentId && api.deleteHighlight(currentId, card.id).then(() => loadRoom(currentId)).catch((err) => setError(err.message))}>移除</Button>
                </div>
              </article>
            ))}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={splitsOpen} onOpenChange={setSplitsOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>分歧</DialogTitle>
            <DialogDescription>{splits?.notice}</DialogDescription>
          </DialogHeader>
          {splits && splits.items.length === 0 && <p data-testid="splits-empty">没有显式的质疑或反驳。这里不编共识。</p>}
          <div className="grid gap-3">
            {(splits?.items || []).map((item) => (
              <article key={item.message_id} data-testid="split-card" className="rounded-xl border p-3 text-sm">
                <p className="text-xs text-[#9a3412]">{item.kind} · {item.label} · 不是事实核查</p>
                <p className="mt-2">{item.source_nickname}：{item.source_excerpt}</p>
                <p className="mt-1">{item.nickname}：{item.excerpt}</p>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => jumpTo(item.source_message_id)}>原消息</Button>
                  <Button size="sm" variant="outline" onClick={() => jumpTo(item.message_id)}>这条回复</Button>
                </div>
              </article>
            ))}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={!!favFor} onOpenChange={(open) => { if (!open) setFavFor(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>收藏这句</DialogTitle>
            <DialogDescription>标题和备注只是你的索引。原话仍是讨论观点，不会因此变成事实。</DialogDescription>
          </DialogHeader>
          <label className="grid gap-1 text-sm">标题
            <Input data-testid="fav-title" value={favTitle} maxLength={40} onChange={(event) => setFavTitle(event.target.value)} />
          </label>
          <label className="grid gap-1 text-sm">备注
            <Input data-testid="fav-note" value={favNote} maxLength={200} onChange={(event) => setFavNote(event.target.value)} />
          </label>
          <Button data-testid="save-highlight" onClick={() => {
            if (!currentId || !favFor) return;
            void api.saveHighlight(currentId, { message_id: favFor, title: favTitle, note: favNote }).then(() => {
              setFavFor(null);
              return loadRoom(currentId);
            }).catch((err) => setError(err.message));
          }}>保存卡片</Button>
        </DialogContent>
      </Dialog>
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>设置</DialogTitle>
            <DialogDescription>主题、字号、导出和本机网页桥。手机上点外面或关闭即可回到聊天。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 text-sm">
            <label>外观
              <select data-testid="theme-select" className="mt-1 h-9 w-full rounded-lg border bg-white px-2" value={theme} onChange={(event) => {
                const value = event.target.value as "light" | "dark" | "system";
                setTheme(value);
                applyTheme(value);
              }}>
                <option value="light">浅色</option>
                <option value="dark">深色</option>
                <option value="system">跟随系统</option>
              </select>
            </label>
            <label>对话字号
              <select data-testid="text-size" className="mt-1 h-9 w-full rounded-lg border bg-white px-2" value={textSize} onChange={(event) => {
                setTextSize(event.target.value);
                applyText(event.target.value);
              }}>
                <option value="compact">紧凑</option>
                <option value="normal">标准</option>
                <option value="large">大</option>
              </select>
            </label>
            <p className="text-xs text-[#6b6258]">Enter 发送，Shift+Enter 换行。输入法组合过程中不会发送。</p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" data-testid="export-md" onClick={() => downloadRoom("md", currentId, messages, highlights)}>导出 Markdown</Button>
              <Button size="sm" variant="outline" data-testid="export-json" onClick={() => downloadRoom("json", currentId, messages, highlights)}>导出 JSON</Button>
            </div>
            <p className="text-xs text-[#6b6258]">导出只有当前房间的公开消息，不含配对令牌或密钥。</p>
            <Button size="sm" variant="secondary" data-testid="pair-code" onClick={() => void api.pairCode().then((item) => setPairCode(item.code)).catch((err) => setError(err.message))}>生成本机配对码</Button>
            <Button size="sm" variant="outline" onClick={() => { setSettingsOpen(false); setConnectOpen(true); }}>连接网页 AI</Button>
            {pairCode && <p data-testid="pair-code-value">配对码 {pairCode}。粘贴到扩展弹窗。令牌不会出现在这里或聊天记录里。五分钟内有效，用一次即失效。</p>}
            <p className="text-xs text-[#6b6258]">手机可以打开群聊页面。网页发送要在开着扩展的这台电脑上完成。元宝和智谱在这台环境没有完成游客发送，不会自动发到登录页。</p>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={connectOpen} onOpenChange={setConnectOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>连接网页 AI</DialogTitle>
            <DialogDescription>只在你这台电脑上、你点过授权的标签页里发送。扩展不读取 Cookie。</DialogDescription>
          </DialogHeader>
          <ol className="list-decimal space-y-2 pl-4 text-sm leading-6" data-testid="connect-steps">
            <li>在设置里生成本机配对码，粘贴到扩展弹窗并点配对。令牌只留在扩展里，不会进聊天。</li>
            <li>在成员里添加「网页会话」。选来源，填写页面地址和绑定键。需要房间代发时打开受控自动发送，然后保存。</li>
            <li>保存后卡片是「已配置，等待扩展绑定」。扩展绑定当前标签页并保持打开，心跳到达后才变成「已绑定标签页」。大约 20 秒没有心跳则是「掉线」。</li>
            <li>用普通 Chrome 打开那个页面。扩展弹窗填同一组 ID 和绑定键，点绑定当前标签页。元宝、智谱等要在这时允许该站点，扩展才会装上内容脚本。</li>
            <li>夹具地址是 http://127.0.0.1:43124/fixture/chat 。Gemini 游客页可以绑定。元宝和智谱可以保存绑定，但公开回复的正文位置还没核实，房间不会自动点击发送。</li>
          </ol>
        </DialogContent>
      </Dialog>
      <Dialog open={memberOpen} onOpenChange={setMemberOpen}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editingId ? "编辑成员" : "添加成员"}</DialogTitle>
            <DialogDescription>同一个模型 ID 可以有多个角色。演示提供方不能填真实模型 ID。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <Label>昵称</Label>
            <Input data-testid="member-nickname" value={memberForm.nickname} onChange={(event) => setMemberForm({ ...memberForm, nickname: event.target.value })} />
            <Label>角色</Label>
            <Input data-testid="member-role" value={memberForm.role_name} onChange={(event) => setMemberForm({ ...memberForm, role_name: event.target.value })} />
            <Label>人设</Label>
            <Textarea value={memberForm.persona} onChange={(event) => setMemberForm({ ...memberForm, persona: event.target.value })} />
            <Label>提供方</Label>
            <select
              data-testid="member-provider"
              className="h-9 rounded-lg border bg-white px-2 text-sm"
              value={memberForm.provider}
              onChange={(event) => {
                const provider = event.target.value;
                const preset = catalog.find((item) => item.provider === provider);
                const site = memberForm.web_site || "fixture";
                setMemberForm({
                  ...memberForm,
                  provider,
                  model_id: preset?.model_id || memberForm.model_id,
                  api_key_env: preset?.key_env || "",
                  web_tab_key: provider === "web" && !memberForm.web_tab_key ? freshTabKey(site) : memberForm.web_tab_key,
                });
              }}
            >
              {catalog.map((item) => (
                <option key={item.provider} value={item.provider}>
                  {item.label} · {item.note}
                </option>
              ))}
            </select>
            <Label>精确模型 ID</Label>
            <Input data-testid="member-model" value={memberForm.model_id} onChange={(event) => setMemberForm({ ...memberForm, model_id: event.target.value })} />
            <Label>API Base（可选）</Label>
            <Input value={memberForm.api_base} onChange={(event) => setMemberForm({ ...memberForm, api_base: event.target.value })} />
            {memberError && <p data-testid="member-error" className="rounded-lg bg-[#fee4e2] px-3 py-2 text-sm text-[#b42318]">{memberError}</p>}
            <Label>密钥变量名（不在这里填密钥）</Label>
            <Input value={memberForm.api_key_env} onChange={(event) => setMemberForm({ ...memberForm, api_key_env: event.target.value })} />
            {memberForm.provider === "web" && (
              <div className="grid gap-3 rounded-xl border p-3" data-testid="web-fields">
                <Label>来源</Label>
                <select
                  data-testid="web-site"
                  className="h-9 rounded-lg border bg-white px-2 text-sm"
                  value={memberForm.web_site}
                  onChange={(event) => {
                    const site = WEB_SITES.find((item) => item.id === event.target.value) || WEB_SITES[0];
                    setMemberForm({
                      ...memberForm,
                      web_site: site.id,
                      web_origin: site.origin,
                      model_id: `web:${site.id}`,
                      web_tab_key: memberForm.web_tab_key || freshTabKey(site.id),
                    });
                  }}
                >
                  {WEB_SITES.map((site) => (
                    <option key={site.id} value={site.id}>{site.label}</option>
                  ))}
                </select>
                <Label>页面地址</Label>
                <Input data-testid="web-origin" value={memberForm.web_origin} onChange={(event) => setMemberForm({ ...memberForm, web_origin: event.target.value })} />
                <Label>标签页绑定键</Label>
                <Input data-testid="web-tab-key" value={memberForm.web_tab_key} onChange={(event) => setMemberForm({ ...memberForm, web_tab_key: event.target.value })} />
                <div className="flex items-center justify-between text-sm">
                  <span>受控自动发送</span>
                  <Switch data-testid="web-auto" checked={memberForm.web_auto} onCheckedChange={(value) => setMemberForm({ ...memberForm, web_auto: value })} />
                </div>
                <p className="text-xs text-[#6b6258]">保存后会写入这个成员的网页绑定。绑定键要原样贴进扩展弹窗。元宝和智谱可以先绑定，正文位置未核实之前房间不会自动点击发送。</p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button data-testid="member-save" onClick={() => void saveMember()}>保存成员</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={secretOpen} onOpenChange={setSecretOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>服务器本地密钥</DialogTitle>
            <DialogDescription>只写入后端 secrets 文件，权限 600。界面、Git 和接口响应都不会回显原文。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <select className="h-9 rounded-lg border bg-white px-2 text-sm" value={secretName} onChange={(event) => setSecretName(event.target.value)}>
              {secretState.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name} {item.configured ? "已配置" : "未配置"}
                </option>
              ))}
            </select>
            <Input type="password" value={secretValue} placeholder="粘贴后立即清空输入框" onChange={(event) => setSecretValue(event.target.value)} />
            <div className="flex items-center justify-between text-sm">
              <span>允许可能计费的调用</span>
              <Switch
                checked={allowPaid}
                onCheckedChange={(value) => {
                  setAllowPaid(value);
                  void api.allowPaid(value);
                }}
              />
            </div>
            <p className="text-xs text-[#6b6258]">默认关闭。未知单价的云端模型在打开前不会被调用。Ollama 和演示不需要这个开关。</p>
          </div>
          <DialogFooter>
            <Button
              onClick={() => {
                void saveSecret();
              }}
            >
              保存到服务器
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Composer({
  busy,
  disabled,
  members,
  groups,
  audience,
  onAudience,
  reply,
  onClearReply,
  onSend,
}: {
  busy: boolean;
  disabled: boolean;
  members: Member[];
  groups: RoomGroup[];
  audience: string;
  onAudience: (value: string) => void;
  reply: ChatMessage | null;
  onClearReply: () => void;
  onSend: (content: string, replyId?: string) => Promise<void>;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const [hasText, setHasText] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);

  function write(next: string) {
    if (box.current) box.current.value = next;
    setHasText(next.trim().length > 0);
  }

  async function send() {
    const content = (box.current?.value ?? "").trim();
    if (!content || disabled) return;
    write("");
    setMentionOpen(false);
    try {
      await onSend(content, reply?.id);
    } catch {
      if (!(box.current?.value ?? "").trim()) write(content);
    }
  }

  return (
    <footer className="border-t border-[#e4d8c8] bg-[#f7f3eb] p-3">
      {reply && (
        <div className="mx-auto mb-2 flex max-w-3xl items-center justify-between rounded-lg bg-white px-3 py-2 text-xs text-[#6b6258]">
          <span className="truncate">回复 {reply.nickname}：{reply.content.slice(0, 42)}</span>
          <button onClick={onClearReply}>取消</button>
        </div>
      )}
      {mentionOpen && (
        <div className="mx-auto mb-2 flex max-w-3xl flex-wrap gap-2">
          {members.filter((item) => item.enabled).map((member) => (
            <Button
              key={member.id}
              size="xs"
              variant="outline"
                onClick={() => {
                const current = box.current?.value ?? "";
                write(`${current}${current.endsWith(" ") || !current ? "" : " "}@${member.nickname} `);
                setMentionOpen(false);
                box.current?.focus();
              }}
            >
              @{member.nickname}
            </Button>
          ))}
        </div>
      )}
      {groups.some((group) => group.status === "active" && group.kind === "discussion") && (
        <div className="mx-auto mb-2 flex max-w-3xl flex-wrap gap-2">
          <label className="text-xs text-[#6b6258]">发给
            <select data-testid="audience" className="ml-2 rounded border bg-white px-2 py-1" value={audience} onChange={(event) => onAudience(event.target.value)}>
              <option value="all">全部分支</option>
              {groups.filter((group) => group.status === "active").map((group) => (
                <option key={group.id} value={`group:${group.id}`}>{group.name}</option>
              ))}
            </select>
          </label>
        </div>
      )}
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <Button type="button" variant="outline" onClick={() => setMentionOpen((value) => !value)}>
          @
        </Button>
        <Textarea
          ref={box}
          data-testid="message-input"
          defaultValue=""
          placeholder={busy ? "插话会进入后续上下文，不会另开一个调度。" : "写给整个房间。Enter 发送，Shift+Enter 换行。"}
          className="min-h-16 bg-white"
          onInput={(event) => setHasText(event.currentTarget.value.trim().length > 0)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || event.keyCode === 229) return;
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <Button data-testid="send-button" disabled={!hasText || disabled} onClick={() => void send()}>
          {busy ? "插话" : "发送"}
        </Button>
      </div>
    </footer>
  );
}

function Meter({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border bg-white px-3 py-2">
      <p className="text-[11px] text-[#6b6258]">{label}</p>
      <p className="font-mono text-sm">{value}</p>
    </div>
  );
}

function Field({ label, value, onChange, disabled }: { label: string; value: string | number; onChange: (value: string) => void; disabled?: boolean }) {
  return (
    <label className="grid gap-1 text-xs text-[#6b6258]">
      {label}
      <Input disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function jumpTo(id: string) {
  document.getElementById(`msg-${id}`)?.scrollIntoView({ block: "center" });
}

function MessageRow({ message, reply, onReply, onFavorite }: { message: ChatMessage; reply?: ChatMessage; onReply: () => void; onFavorite: () => void }) {
  if (message.author_type === "system" && !message.is_summary) {
    return (
      <p data-testid="message" className="px-2 text-center text-xs text-[#6b6258]">
        {message.content}
      </p>
    );
  }
  const discarded = message.status === "discarded" || message.status === "cancelled";
  return (
    <article
      id={`msg-${message.id}`}
      data-message-id={message.id}
      data-testid={message.is_summary ? "summary" : "message"}
      className={`rounded-2xl border bg-white px-3 py-3 ${message.is_summary ? "border-[#9a3412]" : "border-[#eadfce]"} ${discarded ? "opacity-60" : ""}`}
    >
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-full text-sm text-white" style={{ background: message.avatar_color || "#6b6258" }}>
          {(message.nickname || "房").slice(0, 1)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium">{message.nickname || "房间"}</span>
            {message.group_id && <Badge variant="outline">{message.event_kind === "merge" ? "合并" : message.event_kind === "split" ? "拆分" : "本组"}</Badge>}
            {message.role_name && <span className="text-xs text-[#6b6258]">{message.role_name}</span>}
            {message.is_demo && <Badge variant="outline">演示</Badge>}
            {message.is_summary && (
              <Badge>
                {message.provider === "local" ? "本地回顾" : message.is_demo ? "演示总结" : "模型综合"}
              </Badge>
            )}
            {message.status === "streaming" && <Badge variant="secondary">正在说</Badge>}
            {message.status === "error" && <Badge variant="destructive">失败</Badge>}
            {discarded && <Badge variant="secondary">{message.status === "cancelled" ? "已取消" : "已丢弃"}</Badge>}
          </div>
          <p className="mt-0.5 font-mono text-[11px] text-[#6b6258]">
            {message.provider || "room"} / {shownModel(message)}
            {message.round_number ? ` · 第 ${message.round_number} 轮` : ""}
            {phaseLabel(message.phase) ? ` · ${phaseLabel(message.phase)}` : ""}
            {` · ${clock(message.created_at)}`}
          </p>
          {reply && (
            <p className="mt-2 truncate rounded-lg bg-[#f6f1e8] px-2 py-1 text-xs text-[#6b6258]">
              回复 {reply.nickname}：{reply.content.slice(0, 48)}
            </p>
          )}
          <div className={`mt-2 text-sm leading-6 ${message.status === "error" ? "text-[#b42318]" : ""} ${discarded ? "line-through" : ""}`}>
            {message.content ? <RichText text={message.content} /> : (message.status === "streaming" ? "…" : "")}
          </div>
          {message.content && message.author_type !== "system" && (
            <button
              className="mt-2 text-xs text-[#9a3412]"
              onClick={() => void navigator.clipboard.writeText(message.content)}
            >
              复制
            </button>
          )}
          {message.discarded_reason && <p className="mt-1 text-[11px] text-[#6b6258]">标记：{message.discarded_reason}</p>}
          {message.suggest_next_nickname && <p className="mt-1 text-[11px] text-[#6b6258]">建议下一位：{message.suggest_next_nickname}（仅供调度参考）</p>}
          {message.author_type !== "system" && message.status === "complete" && (
            <span className="mt-2 flex gap-3">
              <button data-testid="reply-button" className="text-xs text-[#9a3412]" onClick={onReply}>回复</button>
              <button data-testid="favorite-button" className="text-xs text-[#9a3412]" onClick={onFavorite}>收藏</button>
            </span>
          )}
        </div>
      </div>
    </article>
  );
}
