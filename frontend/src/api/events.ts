import { createEventSource } from "./client";

export function createSessionEventSource(
  sessionId: string,
  options: { baseUrl?: string } = {},
): EventSource {
  return createEventSource(`/api/sessions/${sessionId}/events/stream`, options);
}
