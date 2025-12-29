import { RealtimeClient, type ActivityEventV1 } from "@sdk";

const defaultCentrifugoUrl =
  import.meta.env.VITE_CENTRIFUGO_URL ||
  "ws://localhost:8001/connection/websocket";

export const createRealtimeClient = (url?: string) =>
  new RealtimeClient(url || defaultCentrifugoUrl);

export type RealtimeHandler = (event: ActivityEventV1) => void;
