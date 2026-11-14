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
import { api, eventUrl } from "@/lib/api";
import type { CatalogItem, ChatMessage, Member, Session } from "@/lib/types";

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

const emptyMember = {
  nickname: "",
  role_name: "",
  persona: "",
  provider: "demo",
  model_id: "demo-synthesizer-v1",
  api_base: "",
  api_key_env: "",
  enabled: true,
};

export function ChatApp() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pane, setPane] = useState<"chat" | "people" | "run">("chat");
  const [sideTab, setSideTab] = useState<"rooms" | "members" | "records">("rooms");
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  const [memberOpen, setMemberOpen] = useState(false);
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
    const [detail, msgs] = await Promise.all([api.session(id), api.messages(id)]);
    setSession(detail.session);
    setMembers(detail.members);
    setMessages(msgs);
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
      await api.send(currentId, content.trim(), replyId, session?.mode);
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
    setMemberForm({ ...emptyMember, model_id: preset?.model_id || "demo-synthesizer-v1" });
    setMemberOpen(true);
  }

  function openEditMember(member: Member) {
    setEditingId(member.id);
    setMemberForm({
      nickname: member.nickname,
      role_name: member.role_name,
      persona: member.persona,
      provider: member.provider,
      model_id: member.model_id,
      api_base: member.api_base || "",
      api_key_env: member.api_key_env || "",
      enabled: member.enabled,
    });
    setMemberOpen(true);
  }

  async function saveMember() {
    if (!currentId) return;
    const body = {
      ...memberForm,
      api_base: memberForm.api_base || null,
      api_key_env: memberForm.api_key_env || null,
    };
    try {
      if (editingId) await api.patchMember(editingId, body);
      else await api.addMember(currentId, body);
      setMemberOpen(false);
      await loadRoom(currentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "成员保存失败");
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
    <div className="flex h-dvh flex-col bg-[#efe8dc] text-[#1c1915]">
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
              </div>
            )}
            {sideTab !== "members" && sessions.length === 0 && <p className="px-2 text-sm text-[#d9cbb8]">还没有房间。</p>}
          </ScrollArea>
        </aside>

        <main className={`${pane === "chat" ? "flex" : "hidden"} min-h-0 min-w-0 flex-col lg:flex`}>
          <header className="border-b border-[#e4d8c8] bg-[#f7f3eb] px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="serif text-2xl">{session?.title || "选择一个房间"}</h2>
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
            {session && messages.length === 0 && (
              <p className="mx-auto mt-10 max-w-lg text-center text-sm leading-6 text-[#6b6258]">
                写下一句。启用的成员会先独立回答，彼此看不到这一轮正在生成的内容；之后才能引用公开发言。
              </p>
            )}
            <div className="mx-auto flex max-w-3xl flex-col gap-3">
              {messages.map((message) => (
                <MessageRow key={message.id} message={message} reply={message.reply_to_id ? byId.get(message.reply_to_id) : undefined} onReply={() => setReplyTo(message)} />
              ))}
              <div ref={bottomRef} />
            </div>
          </div>
          <Composer
            busy={!!busy}
            disabled={!currentId}
            members={members}
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
                <Meter label="token" value={String(session?.run_tokens || 0)} />
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
                  value={settings.summary_mode === "member" ? settings.summary_member_id : "local"}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value === "local") setSettings({ ...settings, summary_mode: "local", summary_member_id: "" });
                    else setSettings({ ...settings, summary_mode: "member", summary_member_id: value });
                  }}
                >
                  <option value="local">本地回顾，不额外请求模型</option>
                  {members.map((member) => (
                    <option key={member.id} value={member.id}>
                      由 {member.nickname} 总结（占用 1 条额度）
                    </option>
                  ))}
                </select>
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
                setMemberForm({
                  ...memberForm,
                  provider,
                  model_id: preset?.model_id || memberForm.model_id,
                  api_key_env: preset?.key_env || "",
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
            <Label>密钥变量名（不在这里填密钥）</Label>
            <Input value={memberForm.api_key_env} onChange={(event) => setMemberForm({ ...memberForm, api_key_env: event.target.value })} />
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
  reply,
  onClearReply,
  onSend,
}: {
  busy: boolean;
  disabled: boolean;
  members: Member[];
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

function MessageRow({ message, reply, onReply }: { message: ChatMessage; reply?: ChatMessage; onReply: () => void }) {
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
            {message.role_name && <span className="text-xs text-[#6b6258]">{message.role_name}</span>}
            {message.is_demo && <Badge variant="outline">演示</Badge>}
            {message.is_summary && (
              <Badge>{message.provider === "local" ? "本地回顾" : "成员总结"}</Badge>
            )}
            {message.status === "streaming" && <Badge variant="secondary">正在说</Badge>}
            {message.status === "error" && <Badge variant="destructive">失败</Badge>}
            {discarded && <Badge variant="secondary">{message.status === "cancelled" ? "已取消" : "已丢弃"}</Badge>}
          </div>
          <p className="mt-0.5 font-mono text-[11px] text-[#6b6258]">
            {message.provider || "room"} / {message.model_id || "-"}
            {message.round_number ? ` · 第 ${message.round_number} 轮` : ""}
            {phaseLabel(message.phase) ? ` · ${phaseLabel(message.phase)}` : ""}
            {` · ${clock(message.created_at)}`}
          </p>
          {reply && (
            <p className="mt-2 truncate rounded-lg bg-[#f6f1e8] px-2 py-1 text-xs text-[#6b6258]">
              回复 {reply.nickname}：{reply.content.slice(0, 48)}
            </p>
          )}
          <p className={`mt-2 whitespace-pre-wrap text-sm leading-6 ${message.status === "error" ? "text-[#b42318]" : ""} ${discarded ? "line-through" : ""}`}>
            {message.content || (message.status === "streaming" ? "…" : "")}
          </p>
          {message.discarded_reason && <p className="mt-1 text-[11px] text-[#6b6258]">标记：{message.discarded_reason}</p>}
          {message.suggest_next_nickname && <p className="mt-1 text-[11px] text-[#6b6258]">建议下一位：{message.suggest_next_nickname}（仅供调度参考）</p>}
          {message.author_type !== "system" && message.status === "complete" && (
            <button data-testid="reply-button" className="mt-2 text-xs text-[#9a3412]" onClick={onReply}>
              回复
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
