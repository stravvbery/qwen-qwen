export interface ModelInfo {
  id: string;
  label: string;
  description: string;
  provider: "fireworks" | "freetheai";
  context_length: number | null;
  supports_reasoning: boolean;
  supports_vision: boolean;
}

export interface Message {
  id: string;
  chat_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  reasoning?: string | null;
  model?: string | null;
  attachments?: string[] | null;
  created_at: string;
  /** Gemini 3.1 pool variant (1|2|3), only set client-side. */
  variant?: number | null;
}

export interface Chat {
  id: string;
  title: string;
  model: string;
  system_prompt?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatDetail extends Chat {
  messages: Message[];
}

export type DesignVariantId = "legacy" | "update2" | "zeroSugar";

export type ResponseModeId =
  | "normal"
  | "coder"
  | "teacher"
  | "reviewer"
  | "creative"
  | "brief"
  | "researcher";
