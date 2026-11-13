import { checkApi, logClientEvent, requestAction, type ActionResult, type ClientLogEvent, type LogContext, type LogDetails, type StepResponse } from "./api";
import { HabitatWorld, type ExecutionResult, type TableSide } from "./world";
import "./style.css";

const byId = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing UI element: ${id}`);
  return element as T;
};

const world = new HabitatWorld(byId("scene-mount"));
const apiStatus = byId("api-status");
const sceneState = byId("scene-state");
const activityLog = byId("activity-log");
const stepCount = byId("step-count");
const roverState = byId("rover-state");
const instruction = byId<HTMLTextAreaElement>("instruction");
const runButton = byId<HTMLButtonElement>("run-mission");
const runLabel = byId("run-label");
const runIcon = byId("run-icon");
const stopButton = byId<HTMLButtonElement>("stop-mission");
const missionLog = byId("mission-log");
const maxMissionLogEntries = 200;
let previousActionResult: ActionResult | null = null;
let currentAbort: AbortController | null = null;
let activeRun = 0;
let running = false;
let liveContext: LogContext = {};
let lastFailureSignature: string | null = null;
let repeatedFailureCount = 0;

function formatLogDetails(details: LogDetails, separator = "\n"): string {
  return Object.entries(details).map(([key, value]) => {
    const formatted = typeof value === "number" && !Number.isInteger(value) ? value.toFixed(2) : value;
    return `${key.replace(/_/g, " ")}: ${formatted ?? "none"}`;
  }).join(separator);
}

function describeMissionEvent(entry: ClientLogEvent): { label: string; message: string; tone: string } | null {
  const { event, details } = entry;
  if (event === "mission.started" || event === "mission.rejected") {
    return { label: "INSTRUCTION", message: formatLogDetails(details), tone: "instruction" };
  }
  if (event === "web.request") {
    return { label: "VLM / REQUEST", message: formatLogDetails(details), tone: "request" };
  }
  if (event === "web.response") {
    return { label: "VLM / RESPONSE", message: formatLogDetails(details), tone: "response" };
  }
  if (event === "decision.applied") {
    const target = details.target_id ? ` → ${details.target_id}` : "";
    const override = details.target_overridden === true
      ? `\nTarget changed from ${details.raw_target_id ?? "none"} by the instruction rule.`
      : "";
    return { label: "CONTROLLER / ACTION", message: `${details.action}${target}${override}`, tone: "controller" };
  }
  if (event === "rover.phase") {
    return { label: "ROVER / PHASE", message: String(details.phase), tone: "rover" };
  }
  if (event === "rover.waypoint_reached") {
    const x = typeof details.x === "number" ? details.x.toFixed(2) : details.x;
    const z = typeof details.z === "number" ? details.z.toFixed(2) : details.z;
    return { label: "ROVER / WAYPOINT", message: `${details.waypoint}/${details.total} · X ${x}, Z ${z}`, tone: "rover" };
  }
  if (event.startsWith("rover.")) {
    return { label: `ROVER / ${event.slice(6).replace(/_/g, " ").toUpperCase()}`, message: formatLogDetails(details, " · "), tone: "rover" };
  }
  if (event === "ui.message") {
    if (details.kind === "is-model") return null;
    if (details.kind === "is-success" && typeof details.message === "string" && !details.message.startsWith("Task verified:")) return null;
    if (details.message === "Local stop issued. Late decisions will be ignored.") return null;
    const tone = details.kind === "is-error" ? "error" : details.kind === "is-success" ? "success" : "system";
    return { label: tone.toUpperCase(), message: String(details.message), tone };
  }
  if (event === "web.request_failed" && details.cancelled === true) {
    return { label: "VLM / CANCELLED", message: "Stopped waiting for the response; model inference may continue.", tone: "system" };
  }
  if (event === "web.request_failed" || event === "decision.stale") {
    return { label: "ERROR", message: formatLogDetails(details), tone: "error" };
  }
  if (event === "mission.cancelled") {
    return { label: "MISSION / CANCELLED", message: "Local stop issued. Late decisions will be ignored.", tone: "system" };
  }
  if (event === "mission.ended") {
    return { label: "MISSION / ENDED", message: formatLogDetails(details, " · "), tone: "system" };
  }
  return null;
}

function appendMissionLog(entry: ClientLogEvent): void {
  const presentation = describeMissionEvent(entry);
  if (!presentation) return;
  const follow = missionLog.scrollHeight - missionLog.scrollTop - missionLog.clientHeight < 24;
  missionLog.querySelector(".mission-log-empty")?.remove();

  const row = document.createElement("div");
  row.className = `mission-log-entry is-${presentation.tone}`;
  const meta = document.createElement("div");
  meta.className = "mission-log-meta";
  const label = document.createElement("strong");
  label.textContent = presentation.label;
  const sequence = document.createElement("span");
  sequence.textContent = `#${entry.sequence}`;
  const time = document.createElement("time");
  time.dateTime = entry.occurred_at;
  time.textContent = new Date(entry.occurred_at).toLocaleTimeString([], { hour12: false });
  meta.append(label, sequence, time);
  const message = document.createElement("div");
  message.className = "mission-log-message";
  message.textContent = presentation.message;
  row.append(meta, message);
  missionLog.append(row);
  while (missionLog.children.length > maxMissionLogEntries) missionLog.firstElementChild?.remove();
  if (follow) missionLog.scrollTop = missionLog.scrollHeight;
}

function logEvent(message: string, kind = "normal", context: LogContext = liveContext): void {
  logClientEvent("ui.message", { message, kind }, context);
  const time = new Date().toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });
  const row = document.createElement("div");
  row.className = `log-entry ${kind}`;
  const timestamp = document.createElement("span");
  timestamp.className = "log-time";
  timestamp.textContent = time;
  const text = document.createElement("span");
  text.textContent = message;
  row.append(timestamp, text);
  activityLog.prepend(row);
  while (activityLog.children.length > 4) activityLog.lastElementChild?.remove();
}

function setSceneStatus(text: string, active = false): void {
  sceneState.textContent = text.toUpperCase();
  sceneState.parentElement?.classList.toggle("is-active", active);
}

function setRunButtonBusy(busy: boolean): void {
  runButton.disabled = busy;
  runButton.classList.toggle("is-loading", busy);
  runLabel.textContent = busy ? "ASKING QWEN" : "ASK VLM";
  runIcon.textContent = busy ? "" : "▶";
}

function syncWorldReadout(): void {
  const coordinates = world.getAgentCoordinates();
  byId("coord-x").textContent = coordinates.x.toFixed(1);
  byId("coord-z").textContent = coordinates.z.toFixed(1);
  const held = world.getHeldObjectId();
  roverState.textContent = held ? `CARRYING / ${held}` : "PARKED / EMPTY";
}

function formatAction(result: StepResponse): string {
  const { action, target_id } = result.proposal;
  return target_id ? `${action} → ${target_id}` : action;
}

function toActionResult(actionId: string, result: ExecutionResult): ActionResult {
  return {
    action_id: actionId,
    status: result.status,
    ...(result.target_id ? { target_id: result.target_id } : {}),
    ...(result.error_code ? { error_code: result.error_code } : {}),
  };
}

function logExecutionResult(result: ExecutionResult, context: LogContext): void {
  logClientEvent("rover.action_result", {
    status: result.status, target_id: result.target_id ?? null,
    error_code: result.error_code ?? null, message: result.message,
    held_object_id: world.getHeldObjectId(), ...world.getAgentCoordinates(),
  }, context);
}

function expectedTargetFor(text: string): string {
  const normalized = text.toLowerCase();
  const explicitId = normalized.match(/\bobject_0[123]\b/)?.[0];
  if (explicitId) return explicitId;
  if (normalized.includes("red")) return "object_02";
  if (normalized.includes("yellow")) return "object_03";
  return "object_01";
}

function expectedPlatformFor(text: string): string {
  return /\b(?:second|2nd)\s+(?:room|delivery\s+platform|platform)\b|\broom\s*(?:2|02|two)\b|\b(?:delivery_02|other room)\b/i.test(text)
    ? "delivery_02" : "delivery_01";
}

async function runMission(): Promise<void> {
  const taskText = instruction.value.trim();
  if (!taskText || running) return;
  const requestedSide = taskText.match(/\b(north|south|east|west)\s+side\s+of\s+(?:the\s+)?table\b/i)?.[1]?.toLowerCase();
  const tableSide = requestedSide as TableSide | undefined;
  const expectedTargetId = expectedTargetFor(taskText);
  const expectedPlatformId = expectedPlatformFor(taskText);
  const heldObjectId = world.getHeldObjectId();
  if (heldObjectId && heldObjectId !== expectedTargetId) {
    logClientEvent("mission.rejected", { instruction: taskText, held_object_id: heldObjectId, expected_target_id: expectedTargetId });
    logEvent(`Cannot deliver ${expectedTargetId} while carrying ${heldObjectId}.`, "is-error");
    setSceneStatus("wrong container");
    return;
  }
  running = true;
  let currentStep = 0;
  previousActionResult = null;
  lastFailureSignature = null;
  repeatedFailureCount = 0;
  activeRun += 1;
  const thisRun = activeRun;
  const sessionId = crypto.randomUUID();
  const missionContext = { session_id: sessionId };
  liveContext = missionContext;
  logClientEvent("mission.started", {
    instruction: taskText, expected_target_id: expectedTargetId,
    platform_id: expectedPlatformId, table_side: tableSide ?? null,
  }, missionContext);
  currentAbort = new AbortController();
  setRunButtonBusy(true);
  stopButton.disabled = false;
  instruction.disabled = true;
  byId("last-decision").textContent = "PENDING";
  setSceneStatus("capturing", true);
  logEvent("Mission opened. Capturing current habitat view.", "normal", missionContext);

  try {
    for (let observationId = 0; observationId < 12; observationId += 1) {
      if (thisRun !== activeRun || currentAbort.signal.aborted) break;
      currentStep = observationId + 1;
      stepCount.textContent = String(currentStep).padStart(2, "0");
      setSceneStatus(observationId === 0 ? "vision request" : "next decision", true);
      const requestId = crypto.randomUUID();
      const requestContext = { ...missionContext, request_id: requestId, observation_id: observationId };
      liveContext = requestContext;
      const requestStartedAt = Date.now();
      const requestTimer = window.setInterval(() => {
        const elapsedSeconds = Math.floor((Date.now() - requestStartedAt) / 1000);
        setSceneStatus(`VLM / ${elapsedSeconds}s`, true);
      }, 1000);
      let response: StepResponse;
      try {
        response = await requestAction({
          session_id: sessionId,
          request_id: requestId,
          observation_id: observationId,
          instruction: taskText,
          image_media_type: "image/jpeg",
          image_base64: world.captureJpeg(),
          visible_targets: world.getVisibleTargets(),
          held_object_id: world.getHeldObjectId(),
          previous_action_result: previousActionResult,
        }, currentAbort.signal);
      } finally {
        window.clearInterval(requestTimer);
      }

      if (response.session_id !== sessionId || response.request_id !== requestId || response.observation_id !== observationId) {
        logClientEvent("decision.stale", { message: "Rejected mismatched response identifiers." }, requestContext);
        throw new Error("Rejected stale or mismatched model response.");
      }
      if (thisRun !== activeRun) break;

      const context = { ...requestContext, action_id: response.action_id };
      liveContext = context;
      const proposal = { ...response.proposal };
      if (!world.getHeldObjectId() && (proposal.action === "navigate_to" || proposal.action === "pick_up")) {
        proposal.target_id = expectedTargetId;
      }
      if (world.getHeldObjectId() && (proposal.action === "navigate_to" || proposal.action === "place_on")) {
        proposal.target_id = expectedPlatformId;
      }
      const decision = { ...response, proposal };
      logClientEvent("decision.applied", {
        raw_action: response.proposal.action, raw_target_id: response.proposal.target_id ?? null,
        action: proposal.action, target_id: proposal.target_id ?? null,
        target_overridden: response.proposal.target_id !== proposal.target_id,
      }, context);

      logEvent(`Qwen ${decision.inference_ms} ms / ${formatAction(decision)}`, "is-model", context);
      byId("last-decision").textContent = formatAction(decision).toUpperCase();
      if (decision.proposal.action === "finish") {
        if (world.isDelivered(expectedTargetId, expectedPlatformId)) {
          setSceneStatus("verified", true);
          logEvent(`Task verified: ${expectedTargetId} is on ${expectedPlatformId}.`, "is-success", context);
          break;
        }
        previousActionResult = toActionResult(decision.action_id, {
          status: "failed",
          error_code: "premature_finish",
          message: "Task objective is not complete.",
        });
        logClientEvent("mission.finish_rejected", { expected_target_id: expectedTargetId, platform_id: expectedPlatformId }, context);
        logEvent("Finish rejected: the requested container has not been delivered.", "is-error", context);
        continue;
      }
      if (decision.proposal.action === "stop") {
        world.stopMovement();
        previousActionResult = toActionResult(decision.action_id, { status: "cancelled", message: "Stopped by model proposal." });
        logClientEvent("mission.model_stop", {}, context);
        logEvent("The model proposed stop; task ended.", "is-error", context);
        break;
      }

      if (decision.proposal.action === "pick_up" || (world.getHeldObjectId()
          && (decision.proposal.action === "navigate_to" || decision.proposal.action === "place_on"))) {
        const targetId = world.getHeldObjectId() ?? decision.proposal.target_id ?? "";
        logClientEvent("rover.action_started", { action: "pick_and_place", target_id: targetId, platform_id: expectedPlatformId }, context);
        const result = await world.executePickAndPlace(targetId, (phase) => {
          setSceneStatus(phase, true);
          logClientEvent("rover.phase", { phase }, context);
          logEvent(phase, "is-model", context);
        }, tableSide, expectedPlatformId, context);
        logExecutionResult(result, context);
        if (thisRun !== activeRun) break;
        previousActionResult = toActionResult(decision.action_id, result);
        syncWorldReadout();
        logEvent(result.message, result.status === "failed" ? "is-error" : "is-success", context);
        if (result.status === "succeeded" && world.isDelivered(expectedTargetId, expectedPlatformId)) {
          setSceneStatus("verified", true);
          logEvent(`Task verified: ${expectedTargetId} is on ${expectedPlatformId}.`, "is-success", context);
          break;
        }
        if (result.status !== "succeeded") break;
        logEvent(`Wrong object delivered; expected ${expectedTargetId}.`, "is-error", context);
        break;
      }

      setSceneStatus(decision.proposal.action, true);
      logClientEvent("rover.action_started", { action: proposal.action, target_id: proposal.target_id ?? null }, context);
      const result = await world.execute(decision.proposal, context);
      logExecutionResult(result, context);
      previousActionResult = toActionResult(decision.action_id, result);
      syncWorldReadout();
      logEvent(result.message, result.status === "failed" ? "is-error" : "is-success", context);
      if (result.status === "failed" && result.error_code) {
        const failureSignature = `${decision.proposal.action}:${decision.proposal.target_id ?? ""}:${result.error_code}`;
        repeatedFailureCount = failureSignature === lastFailureSignature ? repeatedFailureCount + 1 : 1;
        lastFailureSignature = failureSignature;
        if (repeatedFailureCount >= 2) {
          logEvent(`Repeated ${result.error_code}; mission stopped to prevent an action loop.`, "is-error", context);
          break;
        }
      } else {
        lastFailureSignature = null;
        repeatedFailureCount = 0;
      }
      if (result.status === "cancelled") break;
    }
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")) {
      logEvent(error instanceof Error ? error.message : "Mission failed.", "is-error", missionContext);
      setSceneStatus("link error");
    }
  } finally {
    logClientEvent("mission.ended", {
      observations: currentStep, superseded: thisRun !== activeRun,
      verified: thisRun === activeRun && world.isDelivered(expectedTargetId, expectedPlatformId),
    }, missionContext);
    if (thisRun === activeRun) {
      running = false;
      currentAbort = null;
      setRunButtonBusy(false);
      stopButton.disabled = true;
      instruction.disabled = false;
      syncWorldReadout();
      if (sceneState.textContent !== "VERIFIED" && sceneState.textContent !== "LINK ERROR") setSceneStatus("standby");
      liveContext = {};
    }
  }
}

function stopMission(): void {
  if (!running) return;
  logClientEvent("mission.cancelled", { held_object_id: world.getHeldObjectId(), ...world.getAgentCoordinates() }, liveContext);
  activeRun += 1;
  currentAbort?.abort();
  currentAbort = null;
  world.stopMovement();
  running = false;
  setRunButtonBusy(false);
  stopButton.disabled = true;
  instruction.disabled = false;
  setSceneStatus("cancelled");
  logEvent("Local stop issued. Late decisions will be ignored.", "is-error");
  liveContext = {};
}

async function updateApiStatus(): Promise<void> {
  try {
    const health = await checkApi();
    apiStatus.textContent = health.model_ready ? `${health.model} READY` : `${health.model} OFFLINE`;
    apiStatus.parentElement?.classList.toggle("is-online", health.model_ready);
  } catch {
    apiStatus.textContent = "API OFFLINE";
    apiStatus.parentElement?.classList.remove("is-online");
  }
}

window.addEventListener("habitat:client-event", (event) => appendMissionLog(event.detail));
runButton.addEventListener("click", () => void runMission());
stopButton.addEventListener("click", stopMission);
void updateApiStatus();
window.setInterval(() => {
  byId("clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
  syncWorldReadout();
}, 500);
window.setInterval(() => void updateApiStatus(), 15_000);

window.addEventListener("beforeunload", () => world.dispose());