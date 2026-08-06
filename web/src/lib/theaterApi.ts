/** 剧场 REST API 客户端 */
import { request } from "./http-client";

export interface World {
  world_id: string;
  name: string;
  worldview: string;
  skill_ids: string[];
  character_ids: string[];
  history: string[];
  created_at: string;
  updated_at: string;
}

export interface TheaterSession {
  session_id: string;
  world_id: string;
  mode: "discuss" | "perform";
  title: string;
  character_ids: string[];
  scene: Record<string, string>;
  pre_read_done: boolean;
  pre_read_steps: Array<{ key: string; label: string; status: string; note?: string }>;
  consensus: string;
  battle_ratio: number;
  status: string;
  created_at: string;
}

export const fetchTheaterWorlds = () =>
  request<{ worlds: World[] }>("/api/theater/worlds");

export const createTheaterWorld = (data: {
  name: string;
  worldview?: string;
  skill_ids?: string[];
}) =>
  request<{ success: boolean; world: World }>("/api/theater/worlds", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateTheaterWorld = (worldId: string, updates: Partial<World>) =>
  request<{ success: boolean; world: World }>(`/api/theater/worlds/${worldId}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });

export const deleteTheaterWorld = (worldId: string) =>
  request<{ success: boolean }>(`/api/theater/worlds/${worldId}`, { method: "DELETE" });

export const createTheaterSession = (data: {
  world_id: string;
  mode: string;
  title: string;
  character_ids: string[];
  scene: Record<string, string>;
  battle_ratio: number;
}) =>
  request<{ success: boolean; session: TheaterSession }>("/api/theater/sessions", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const fetchTheaterSessions = () =>
  request<{ sessions: TheaterSession[] }>("/api/theater/sessions");

export const preReadTheater = (sessionId: string) =>
  request<{ success: boolean; steps: TheaterSession["pre_read_steps"]; consensus: string; session: TheaterSession }>(
    `/api/theater/sessions/${sessionId}/pre-read`,
    { method: "POST" }
  );

export const setTheaterBattleRatio = (sessionId: string, ratio: number) =>
  request<{ success: boolean; ratio: number }>(`/api/theater/sessions/${sessionId}/battle-ratio`, {
    method: "PUT",
    body: JSON.stringify({ ratio }),
  });

export const theaterBattle = (sessionId: string, data: {
  attacker_id: string;
  defender_id?: string;
  action?: string;
  attack_stat?: string;
  defense_stat?: string;
}) =>
  request<{ success: boolean; result: Record<string, unknown> }>(`/api/theater/sessions/${sessionId}/battle`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const backstageChat = (sessionId: string, message: string) =>
  request<{ success: boolean; reply: string }>(`/api/theater/sessions/${sessionId}/backstage`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
