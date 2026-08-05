/** 人物库 REST API 客户端（故事机器 / 圆桌共享） */
import { request } from "./http-client";

export interface Trait {
  name: string;
  id_delta: number;
  ego_delta: number;
  superego_delta: number;
  emotion_amplifier: number;
  regress_rate: number | null;
}

export interface StoryEvent {
  title: string;
  description: string;
  triggers: string[];
  emotion_shift: Record<string, number>;
  ratio_rebase: Record<string, number>;
  decay: number;
  active_count?: number;
}

export interface Character {
  character_id: string;
  name: string;
  base_ratio: { id: number; ego: number; superego: number };
  ratio_descriptions: Record<string, string>;
  traits: Trait[];
  events: StoryEvent[];
  hard_rules: string[];
  soft_rules: string[];
  temperature: number;
  model_name: string | null;
  emotion_state: Record<string, number>;
  pinned_emotion: Record<string, number> | null;
  pinned_ratios: { id: number; ego: number; superego: number } | null;
  current_ratio: { id: number; ego: number; superego: number };
  pressure: number;
  summary: string;
  memory_logs: Array<{
    type: string;
    session_id: string;
    title: string;
    content: string;
    timestamp: string;
  }>;
  chat_history?: Array<{
    user: string;
    assistant: string;
    timestamp: string;
  }>;
  log_path?: string;
}

export interface ChatReply {
  thinking: string;
  expression: string;
  action: string;
  speech: string;
  emotion: Record<string, number>;
}

export interface ChatResult {
  success: boolean;
  reply: ChatReply;
  state: {
    current_ratio: { id: number; ego: number; superego: number };
    emotion_state: Record<string, number>;
    layer: string;
    event_hits: string[];
    violations: string[];
  };
  log_path: string;
}

export interface ChatExportResult {
  success: boolean;
  markdown: string;
  path: string;
}

export const fetchCharacters = () =>
  request<{ characters: Character[]; total: number }>("/characters");

export const saveCharacter = (data: Partial<Character>) =>
  request<{ success: boolean; character: Character }>("/characters", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const deleteCharacter = (id: string) =>
  request<{ success: boolean }>(`/characters/${id}`, { method: "DELETE" });

export const clearCharacterMemory = (id: string) =>
  request<{ success: boolean }>(`/characters/${id}/memory/clear`, {
    method: "POST",
  });

export const chatCharacter = (id: string, message: string, search = false) =>
  request<ChatResult>(`/characters/${id}/chat`, {
    method: "POST",
    body: JSON.stringify({ message, search }),
  });

export const exportCharacterChat = (id: string) =>
  request<ChatExportResult>(`/characters/${id}/chat/export`, {
    method: "POST",
  });

export const openCharacterLog = (id: string) =>
  request<{ success: boolean; log_path: string }>(`/characters/${id}/log/open`, {
    method: "POST",
  });
