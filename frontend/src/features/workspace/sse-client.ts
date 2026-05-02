import { createSessionEventSource as createApiSessionEventSource } from "../../api/events";

export type SessionEventSourceOptions = {
  baseUrl?: string;
};

export function createSessionEventSource(
  sessionId: string,
  options: SessionEventSourceOptions = {},
): EventSource {
  return createApiSessionEventSource(sessionId, options);
}
