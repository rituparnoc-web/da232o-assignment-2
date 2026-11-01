export type TargetCategory = "container" | "platform";

export interface TargetDescriptor {
  target_id: string;
  category: TargetCategory;
  in_interaction_range: boolean;
}

export interface ActionProposal {
  action: "navigate_to" | "pick_up" | "place_on" | "stop" | "finish";
  target_id?: string;
}

export interface ActionResult {
  action_id: string;
  status: "succeeded" | "failed" | "cancelled";
  target_id?: string;
  error_code?: string;
}

export interface StepRequest {
  session_id: string;
  request_id: string;
  observation_id: number;
  instruction: string;
  image_media_type: "image/jpeg";
  image_base64: string;
  visible_targets: TargetDescriptor[];
  held_object_id: string | null;
  previous_action_result: ActionResult | null;
}

export interface StepResponse {
  session_id: string;
  request_id: string;
  observation_id: number;
  action_id: string;
  proposal: ActionProposal;
  inference_ms: number;
}

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function checkApi(): Promise<{ model_ready: boolean; model: string }> {
  const response = await fetch(`${apiBase}/health`);
  if (!response.ok) throw new Error(`API health check failed (${response.status})`);
  return response.json() as Promise<{ model_ready: boolean; model: string }>;
}

export async function requestAction(body: StepRequest, signal: AbortSignal): Promise<StepResponse> {
  const response = await fetch(`${apiBase}/step`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const payload = await response.json() as StepResponse | { error?: { code?: string; message?: string } };
  if (!response.ok) {
    const error = "error" in payload ? payload.error : undefined;
    throw new Error(error?.message ?? `VLM request failed (${response.status})`);
  }
  return payload as StepResponse;
}