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

export interface LogContext {
  session_id?: string;
  request_id?: string;
  observation_id?: number;
  action_id?: string;
}

export type LogDetails = Record<string, string | number | boolean | null>;

const pageId = crypto.randomUUID();
let logSequence = 0;

export function logClientEvent(event: string, details: LogDetails = {}, context: LogContext = {}): void {
  const entry = {
    ...context, event,
    details: Object.fromEntries(Object.entries(details).map(([key, value]) => [
      key, typeof value === "string" ? value.slice(0, 2000) : value,
    ])),
    page_id: pageId,
    sequence: ++logSequence, occurred_at: new Date().toISOString(),
  };
  console.info("[habitat]", entry);
  void fetch(`${apiBase}/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(entry),
    keepalive: true,
  }).then((response) => {
    if (!response.ok) throw new Error(`Live log delivery failed (${response.status})`);
  }).catch((error: unknown) => {
    console.error("Could not forward live event to the backend.", { event, error });
  });
}

export async function checkApi(): Promise<{ model_ready: boolean; model: string }> {
  const response = await fetch(`${apiBase}/health`);
  if (!response.ok) throw new Error(`API health check failed (${response.status})`);
  return response.json() as Promise<{ model_ready: boolean; model: string }>;
}

export async function requestAction(body: StepRequest, signal: AbortSignal): Promise<StepResponse> {
  const context = {
    session_id: body.session_id, request_id: body.request_id, observation_id: body.observation_id,
  };
  logClientEvent("web.request", {
    instruction: body.instruction, image_base64_chars: body.image_base64.length,
    visible_target_count: body.visible_targets.length, held_object_id: body.held_object_id,
  }, context);
  try {
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
    const result = payload as StepResponse;
    logClientEvent("web.response", {
      action: result.proposal.action, target_id: result.proposal.target_id ?? null,
      inference_ms: result.inference_ms,
    }, { ...context, action_id: result.action_id });
    return result;
  } catch (error) {
    logClientEvent("web.request_failed", {
      message: error instanceof Error ? error.message : "Request failed",
      cancelled: signal.aborted,
    }, context);
    throw error;
  }
}