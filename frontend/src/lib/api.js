/**
 * The one place the frontend knows the backend's shape.
 *
 * Everything here is read-only or a chat message. There is deliberately no
 * `deleteMemory` helper: forgetting is a CONFIRM tool, and routing it through
 * an ordinary chat message is what keeps the approval prompt in the loop.
 */

const BASE = process.env.NEXT_PUBLIC_NEXUS_API ?? "http://127.0.0.1:8000";

export const WS_URL = BASE.replace(/^http/, "ws") + "/api/ws";

async function get(path, { signal } = {}) {
  const response = await fetch(`${BASE}${path}`, { signal, cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} responded ${response.status}`);
  }
  return response.json();
}

export async function fetchHealth(options) {
  return get("/health", options);
}

export async function fetchContext(options) {
  return get("/api/context", options);
}

export async function fetchMemories(options) {
  return get("/api/memory", options);
}

export async function fetchObservations(options) {
  return get("/api/observations?limit=50", options);
}

export async function dismissObservation(observationId) {
  const response = await fetch(
    `${BASE}/api/observations/${observationId}/dismiss`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error("Could not dismiss that.");
  return response.json();
}

export async function fetchSuggestions(options) {
  return get("/api/suggestions?limit=20", options);
}

export async function dismissSuggestion(suggestionId) {
  const response = await fetch(
    `${BASE}/api/suggestions/${suggestionId}/dismiss`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error("Could not dismiss that.");
  return response.json();
}

/**
 * Records that a suggestion was taken up. Executes nothing: the caller sends
 * the suggestion's own prompt to /api/chat, which is the only path to an
 * action and keeps the ordinary approval flow in place.
 */
export async function acceptSuggestion(suggestionId) {
  const response = await fetch(
    `${BASE}/api/suggestions/${suggestionId}/accept`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error("Could not accept that.");
  return response.json();
}

export async function fetchTask(taskId, options) {
  return get(`/api/tasks/${taskId}`, options);
}

export async function fetchTrace(taskId, options) {
  return get(`/api/tasks/${taskId}/trace`, options);
}

export async function fetchPending(options) {
  return get("/api/permissions/pending", options);
}

export async function sendMessage(message) {
  const response = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return response.json();
}

export async function resolvePermission(requestId, decision) {
  const response = await fetch(
    `${BASE}/api/permissions/${requestId}/${decision}`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(`Could not ${decision} that request.`);
  }
  return response.json();
}

export async function cancelTask(taskId) {
  const response = await fetch(`${BASE}/api/tasks/${taskId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) throw new Error("Could not cancel that task.");
  return response.json();
}
