/** 故事机器 REST API 客户端 */
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
}

export interface StoryMessage {
  speaker_name: string;
  entry_type: "narrator" | "character" | "director";
  thinking: string;
  expression: string;
  action: string;
  speech: string;
  emotion: Record<string, number>;
  round_number: number;
  timestamp: string;
}

export interface StorySessionDetail {
  session_id: string;
  session_type: string;
  title: string;
  scene: Record<string, string>;
  character_ids: string[];
  narrator_enabled: boolean;
  max_rounds: number;
  status: "waiting" | "discussing" | "paused" | "ended";
  transcript: StoryMessage[];
  current_round: number;
  active_turn: { speaker_name: string; entry_type: string; content: string } | null;
  created_at: string;
  ended_at: string | null;
  characters: Character[];
}

export interface StorySessionSummary {
  session_id: string;
  title: string;
  status: string;
  character_ids: string[];
  current_round: number;
  max_rounds: number;
  transcript_count: number;
  created_at: string;
}

export const fetchCharacters = () =>
  request<{ characters: Character[]; total: number }>("/story/characters");

export const saveCharacter = (data: Partial<Character>) =>
  request<{ success: boolean; character: Character }>("/story/characters", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const deleteCharacter = (id: string) =>
  request<{ success: boolean }>(`/story/characters/${id}`, { method: "DELETE" });

export const fetchStories = () =>
  request<{ sessions: StorySessionSummary[]; total: number }>("/story/sessions");

export const fetchStoryDetail = (id: string) =>
  request<StorySessionDetail>(`/story/sessions/${id}`);

export const createStory = (data: {
  title: string;
  scene: Record<string, string>;
  character_ids: string[];
  max_rounds: number;
  narrator_enabled: boolean;
}) =>
  request<{ success: boolean; session: StorySessionSummary }>("/story/sessions", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const deleteStory = (id: string) =>
  request<{ success: boolean }>(`/story/sessions/${id}`, { method: "DELETE" });

export const startStory = (id: string) =>
  request<{ success: boolean; message: string }>(`/story/sessions/${id}/start`, {
    method: "POST",
  });

export const stopStory = (id: string) =>
  request<{ success: boolean; message: string }>(`/story/sessions/${id}/stop`, {
    method: "POST",
  });

export const pauseStory = (id: string) =>
  request<{ success: boolean; message: string }>(`/story/sessions/${id}/pause`, {
    method: "POST",
  });

export const resumeStory = (id: string) =>
  request<{ success: boolean; message: string }>(`/story/sessions/${id}/resume`, {
    method: "POST",
  });

export const injectStory = (id: string, content: string) =>
  request<{ success: boolean; message: string }>(`/story/sessions/${id}/inject`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });

export const setStoryEmotion = (
  id: string,
  character_id: string,
  emotion?: Record<string, number>,
  ratios?: { id: number; ego: number; superego: number },
  clear = false,
) =>
  request<{ success: boolean }>(`/story/sessions/${id}/emotions`, {
    method: "POST",
    body: JSON.stringify({ character_id, emotion, ratios, clear }),
  });

export const exportStory = (id: string) =>
  request<{ success: boolean; markdown: string }>(`/story/sessions/${id}/export`);

