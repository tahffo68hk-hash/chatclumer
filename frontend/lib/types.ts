export type Session = {
  id: string;
  title: string;
  status: string;
  status_label: string;
  mode: string;
  max_rounds: number;
  max_ai_messages: number;
  max_seconds: number;
  max_tokens: number | null;
  max_cost_usd: number | null;
  summary_mode: string;
  summary_member_id: string | null;
  summary_provider?: string | null;
  summary_model_id?: string | null;
  cross_delay_ms: number;
  room_rule: string;
  stop_on_no_new_point: boolean;
  current_round: number;
  ai_message_count: number;
  run_tokens: number;
  run_tokens_known?: boolean;
  run_cost_usd: number;
  run_cost_known: boolean;
  total_tokens: number;
  total_cost_usd: number;
  context_version: number;
  run_token: string | null;
  end_reason: string | null;
  end_reason_label: string;
  speaking_member_ids: string[];
  speaking_nicknames: string[];
  started_at: string | null;
  deadline_at: string | null;
  message_count?: number;
  member_count?: number;
  created_at: string;
  updated_at: string;
  layout?: string;
};

export type RoomGroup = {
  id: string;
  session_id: string;
  name: string;
  kind: string;
  status: string;
  generation: number;
  settled: boolean;
  member_ids: string[];
};

export type Member = {
  id: string;
  session_id: string;
  nickname: string;
  role_name: string;
  persona: string;
  provider: string;
  model_id: string;
  api_base: string | null;
  api_key_env: string | null;
  enabled: boolean;
  avatar_color: string;
  web_site?: string | null;
  web_origin?: string | null;
  web_tab_key?: string | null;
  web_auto?: boolean;
  web_conversation?: string | null;
  web_link?: string;
  web_health?: WebHealth | null;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  author_type: "user" | "ai" | "system";
  member_id: string | null;
  nickname: string | null;
  role_name: string | null;
  provider: string | null;
  model_id: string | null;
  avatar_color: string | null;
  content: string;
  status: string;
  reply_to_id: string | null;
  round_number: number | null;
  phase: string | null;
  context_version: number;
  suggest_next_nickname: string | null;
  is_demo: boolean;
  is_summary: boolean;
  discarded_reason: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  created_at: string;
  finished_at: string | null;
  group_id?: string | null;
  audience?: string | null;
  event_kind?: string | null;
};

export type HighlightCard = {
  id: string;
  session_id: string;
  message_id: string;
  title: string;
  note: string;
  nickname: string;
  member_id: string | null;
  excerpt: string;
  disclaimer: string;
};

export type SplitItem = {
  kind: string;
  label: string;
  message_id: string;
  source_message_id: string;
  nickname: string;
  source_nickname: string;
  excerpt: string;
  source_excerpt: string;
};

export type CatalogItem = {
  provider: string;
  label: string;
  model_id: string;
  paid: boolean;
  key_env: string;
  base_url?: string;
  note: string;
};

// 扩展的页面检查（不发送）结果，随心跳上报。
export type WebHealth = {
  site: string;
  ok: boolean;
  missing: string[];
  deferred?: string[];
  empty: string[];
  gate: string | null;
  detail: string;
  roles: Record<string, { found: number; index: number }>;
  registry_version: string;
  registry_source: string;
  checked_at: string;
};
