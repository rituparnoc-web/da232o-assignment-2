import { checkApi, requestAction, type ActionResult, type StepResponse } from "./api";
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
const targetList = byId("target-list");
let selectedTarget = "object_01";
let previousActionResult: ActionResult | null = null;
let currentAbort: AbortController | null = null;
let activeRun = 0;
let running = false;
let currentStep = 0;
let lastFailureSignature: string | null = null;
let repeatedFailureCount = 0;

const targetDetails = [
  { id: "object_01", name: "Blue tote", detail: "Chromatic polymer / 12kg", color: "#2777de" },
  { id: "object_02", name: "Red tote", detail: "Thermal seal / 9kg", color: "#e46855" },
  { id: "object_03", name: "Yellow tote", detail: "Survey kit / 6kg", color: "#e5bf49" },
  { id: "delivery_01", name: "Delivery platform", detail: "Transfer zone / bay A", color: "#a5cf74" },
  { id: "delivery_02", name: "Room 2 platform", detail: "Transfer zone / bay B", color: "#a5cf74" },
];

function logEvent(message: string, kind = "normal"): void {
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
  for (const detail of targetDetails) {
    const state = world.getTargetState(detail.id);
    const stateElement = document.querySelector<HTMLElement>(`[data-target-state="${detail.id}"]`);
    if (stateElement) stateElement.textContent = state.toUpperCase();
    const row = document.querySelector<HTMLElement>(`[data-target-id="${detail.id}"]`);
    row?.classList.toggle("is-delivered", state === "delivered");
    row?.classList.toggle("is-held", state === "held");
  }
}

function renderTargetRegistry(): void {
  targetList.replaceChildren();
  for (const [index, target] of targetDetails.entries()) {
    const button = document.createElement("button");
    button.className = `target-row${target.id === selectedTarget ? " is-selected" : ""}`;
    button.type = "button";
    button.dataset.targetId = target.id;
    const swatch = document.createElement("span");
    swatch.className = "target-swatch";
    swatch.style.setProperty("--swatch", target.color);
    const copy = document.createElement("span");
    copy.className = "target-copy";
    const name = document.createElement("strong");
    name.textContent = target.name;
    const sub = document.createElement("small");
    sub.textContent = `${target.id} / ${target.detail}`;
    copy.append(name, sub);
    const state = document.createElement("span");
    state.className = "target-state mono";
    state.dataset.targetState = target.id;
    state.textContent = world.getTargetState(target.id).toUpperCase();
    const number = document.createElement("span");
    number.className = "target-number mono";
    number.textContent = String(index + 1).padStart(2, "0");
    button.append(swatch, copy, state, number);
    button.addEventListener("click", () => {
      selectedTarget = target.id;
      world.setSelectedTarget(target.id);
      renderTargetRegistry();
    });
    targetList.append(button);
  }
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

async function doManualAction(action: { action: "navigate_to" | "pick_up" | "place_on"; target_id: string }): Promise<void> {
  if (running) return;
  setSceneStatus(action.action, true);
  const result = await world.execute(action);
  syncWorldReadout();
  logEvent(result.message, result.status === "failed" ? "is-error" : "is-success");
  setSceneStatus(result.status === "succeeded" ? "standby" : result.error_code ?? "standby");
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
    logEvent(`Cannot deliver ${expectedTargetId} while carrying ${heldObjectId}.`, "is-error");
    setSceneStatus("wrong container");
    return;
  }
  running = true;
  currentStep = 0;
  previousActionResult = null;
  lastFailureSignature = null;
  repeatedFailureCount = 0;
  activeRun += 1;
  const thisRun = activeRun;
  const sessionId = crypto.randomUUID();
  currentAbort = new AbortController();
  setRunButtonBusy(true);
  stopButton.disabled = false;
  instruction.disabled = true;
  byId("last-decision").textContent = "PENDING";
  setSceneStatus("capturing", true);
  logEvent("Mission opened. Capturing current habitat view.");

  try {
    for (let observationId = 0; observationId < 12; observationId += 1) {
      if (thisRun !== activeRun || currentAbort.signal.aborted) break;
      currentStep = observationId + 1;
      stepCount.textContent = String(currentStep).padStart(2, "0");
      setSceneStatus(observationId === 0 ? "vision request" : "next decision", true);
      const requestId = crypto.randomUUID();
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
        throw new Error("Rejected stale or mismatched model response.");
      }
      if (thisRun !== activeRun) break;

      const proposal = response.proposal;
      if (!world.getHeldObjectId() && (proposal.action === "navigate_to" || proposal.action === "pick_up")) {
        proposal.target_id = expectedTargetId;
      }
      if (world.getHeldObjectId() && (proposal.action === "navigate_to" || proposal.action === "place_on")) {
        proposal.target_id = expectedPlatformId;
      }
      const decision = { ...response, proposal };

      logEvent(`Qwen ${decision.inference_ms} ms / ${formatAction(decision)}`, "is-model");
      byId("last-decision").textContent = formatAction(decision).toUpperCase();
      if (decision.proposal.action === "finish") {
        if (world.isDelivered(expectedTargetId, expectedPlatformId)) {
          setSceneStatus("verified", true);
          logEvent(`Task verified: ${expectedTargetId} is on ${expectedPlatformId}.`, "is-success");
          break;
        }
        previousActionResult = toActionResult(decision.action_id, {
          status: "failed",
          error_code: "premature_finish",
          message: "Task objective is not complete.",
        });
        logEvent("Finish rejected: the requested container has not been delivered.", "is-error");
        continue;
      }
      if (decision.proposal.action === "stop") {
        world.stopMovement();
        previousActionResult = toActionResult(decision.action_id, { status: "cancelled", message: "Stopped by model proposal." });
        logEvent("The model proposed stop; task ended.", "is-error");
        break;
      }

      if (decision.proposal.action === "pick_up" || (world.getHeldObjectId()
          && (decision.proposal.action === "navigate_to" || decision.proposal.action === "place_on"))) {
        const targetId = world.getHeldObjectId() ?? decision.proposal.target_id ?? "";
        const result = await world.executePickAndPlace(targetId, (phase) => {
          setSceneStatus(phase, true);
          logEvent(phase, "is-model");
        }, tableSide, expectedPlatformId);
        if (thisRun !== activeRun) break;
        previousActionResult = toActionResult(decision.action_id, result);
        syncWorldReadout();
        logEvent(result.message, result.status === "failed" ? "is-error" : "is-success");
        if (result.status === "succeeded" && world.isDelivered(expectedTargetId, expectedPlatformId)) {
          setSceneStatus("verified", true);
          logEvent(`Task verified: ${expectedTargetId} is on ${expectedPlatformId}.`, "is-success");
          break;
        }
        if (result.status !== "succeeded") break;
        logEvent(`Wrong object delivered; expected ${expectedTargetId}.`, "is-error");
        break;
      }

      setSceneStatus(decision.proposal.action, true);
      const result = await world.execute(decision.proposal);
      previousActionResult = toActionResult(decision.action_id, result);
      syncWorldReadout();
      logEvent(result.message, result.status === "failed" ? "is-error" : "is-success");
      if (result.status === "failed" && result.error_code) {
        const failureSignature = `${decision.proposal.action}:${decision.proposal.target_id ?? ""}:${result.error_code}`;
        repeatedFailureCount = failureSignature === lastFailureSignature ? repeatedFailureCount + 1 : 1;
        lastFailureSignature = failureSignature;
        if (repeatedFailureCount >= 2) {
          logEvent(`Repeated ${result.error_code}; mission stopped to prevent an action loop.`, "is-error");
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
      logEvent(error instanceof Error ? error.message : "Mission failed.", "is-error");
      setSceneStatus("link error");
    }
  } finally {
    if (thisRun === activeRun) {
      running = false;
      currentAbort = null;
      setRunButtonBusy(false);
      stopButton.disabled = true;
      instruction.disabled = false;
      syncWorldReadout();
      if (sceneState.textContent !== "VERIFIED" && sceneState.textContent !== "LINK ERROR") setSceneStatus("standby");
    }
  }
}

function stopMission(): void {
  if (!running) return;
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
}

function bindManualControls(): void {
  byId("navigate-target").addEventListener("click", () => {
    const descriptor = world.getVisibleTargets().find((target) => target.target_id === selectedTarget);
    if (descriptor) void doManualAction({ action: "navigate_to", target_id: selectedTarget });
  });
  byId("pickup-target").addEventListener("click", () => {
    void doManualAction({ action: "pick_up", target_id: selectedTarget });
  });
  byId("place-target").addEventListener("click", () => {
    void doManualAction({ action: "place_on", target_id: selectedTarget.startsWith("delivery_") ? selectedTarget : "delivery_01" });
  });
  const movement: Array<[string, number, number]> = [
    ["move-north", 0, -0.9], ["move-south", 0, 0.9], ["move-west", -0.9, 0], ["move-east", 0.9, 0],
  ];
  for (const [id, dx, dz] of movement) {
    byId(id).addEventListener("click", async () => {
      if (running) return;
      setSceneStatus("manual move", true);
      const result = await world.nudge(dx, dz);
      syncWorldReadout();
      if (result.status === "failed") logEvent(result.message, "is-error");
      setSceneStatus("standby");
    });
  }
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

renderTargetRegistry();
world.setSelectedTarget(selectedTarget);
bindManualControls();
runButton.addEventListener("click", () => void runMission());
stopButton.addEventListener("click", stopMission);
void updateApiStatus();
window.setInterval(() => {
  byId("clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
  syncWorldReadout();
}, 500);
window.setInterval(() => void updateApiStatus(), 15_000);

window.addEventListener("beforeunload", () => world.dispose());