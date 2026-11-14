import type { CatalogItem, ChatMessage, HighlightCard, Member, RoomGroup, Session, SplitItem } from "./types";

const base = process.env.NEXT_PUBLIC_API_BASE || "/backend";

export function apiUrl(path: string) {
  return `${base}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : `请求失败 ${res.status}`);
  }
  return data as T;
}

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  catalog: () => request<{ providers: CatalogItem[] }>("/api/catalog"),
  secrets: () => request<{ secrets: { name: string; configured: boolean }[]; allow_paid: boolean }>("/api/secrets/status"),
  saveSecret: (name: string, value: string) => request("/api/secrets", { method: "PUT", body: JSON.stringify({ name, value }) }),
  allowPaid: (enabled: boolean) => request("/api/runtime/allow-paid", { method: "PUT", body: JSON.stringify({ enabled }) }),
  integrations: () => request<{ qq: { state: string; detail: string }; wechat: { state: string; detail: string } }>("/api/integrations/status"),
  sessions: () => request<Session[]>("/api/sessions"),
  createSession: (body: Record<string, unknown>) => request<Session>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),
  session: (id: string) => request<{ session: Session; members: Member[]; groups?: RoomGroup[] }>(`/api/sessions/${id}`),
  patchSession: (id: string, body: Record<string, unknown>) =>
    request<Session>(`/api/sessions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSession: (id: string) => request(`/api/sessions/${id}`, { method: "DELETE" }),
  addMember: (id: string, body: Record<string, unknown>) =>
    request<Member>(`/api/sessions/${id}/members`, { method: "POST", body: JSON.stringify(body) }),
  patchMember: (id: string, body: Record<string, unknown>) => request<Member>(`/api/members/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  webBind: (id: string, body: { web_site: string; web_origin: string; web_tab_key: string; web_auto: boolean }) =>
    request<Member>(`/api/members/${id}/web-bind`, { method: "POST", body: JSON.stringify(body) }),
  deleteMember: (id: string) => request(`/api/members/${id}`, { method: "DELETE" }),
  messages: (id: string) => request<ChatMessage[]>(`/api/sessions/${id}/messages`),
  send: (id: string, content: string, reply_to_id?: string | null, mode?: string, audience?: string, group_id?: string) =>
    request(`/api/sessions/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content, reply_to_id, mode, audience, group_id }),
    }),
  previewMerge: (id: string, member_ids: string[]) =>
    request<{ note: string; shares: { message_id: string; nickname: string; excerpt: string }[] }>(
      `/api/sessions/${id}/groups/preview`,
      { method: "POST", body: JSON.stringify({ member_ids }) },
    ),
  merge: (id: string, member_ids: string[]) =>
    request(`/api/sessions/${id}/groups/merge`, { method: "POST", body: JSON.stringify({ member_ids }) }),
  split: (id: string, group_id: string, member_ids: string[], carry: "public" | "fresh", web_memory: "rebind" | "retain" = "rebind") =>
    request(`/api/sessions/${id}/groups/${group_id}/split`, {
      method: "POST",
      body: JSON.stringify({ member_ids, carry, web_memory }),
    }),
  pairCode: () => request<{ code: string; expires_at: string }>("/api/ext/code", { method: "POST" }),
  highlights: (id: string) => request<{ cards: HighlightCard[]; disclaimer: string }>(`/api/sessions/${id}/highlights`),
  saveHighlight: (id: string, body: { message_id: string; title: string; note: string }) =>
    request(`/api/sessions/${id}/highlights`, { method: "PUT", body: JSON.stringify(body) }),
  deleteHighlight: (id: string, highlightId: string) =>
    request(`/api/sessions/${id}/highlights/${highlightId}`, { method: "DELETE" }),
  disagreements: (id: string) =>
    request<{ items: SplitItem[]; consensus: never[]; notice: string }>(`/api/sessions/${id}/disagreements`),
  pause: (id: string) => request(`/api/sessions/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request(`/api/sessions/${id}/resume`, { method: "POST" }),
  stop: (id: string) => request(`/api/sessions/${id}/stop`, { method: "POST" }),
};

export function eventUrl(id: string) {
  return apiUrl(`/api/sessions/${id}/events`);
}
