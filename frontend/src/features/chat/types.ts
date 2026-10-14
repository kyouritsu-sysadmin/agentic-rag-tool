import type { Citation as WireCitation, MessageResponse, ThreadResponse, RunResponse } from "@/lib/contracts/api";

export type Citation = WireCitation;
export type StoredMessage = Omit<MessageResponse, "createdAt" | "parent_id" | "status" | "citations"> & {
  createdAt: Date; parent_id?: string | null; status?: string; citations?: Citation[];
};
export type StoredThread = Omit<ThreadResponse, "createdAt" | "title" | "head_id"> & {
  createdAt: Date; title: string | undefined; head_id?: string | null; messages: StoredMessage[];
};
export type Run = Omit<RunResponse, "user_message_id" | "error"> & {
  user_message_id?: string; error?: string | null; message?: StoredMessage | MessageResponse;
};
