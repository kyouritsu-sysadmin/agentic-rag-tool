import { create } from "zustand";
import type { MessageResponse } from "@/lib/contracts/api";
import type { StoredMessage, StoredThread, Run } from "./types";
export type { Citation, StoredMessage, StoredThread, Run } from "./types";
interface State {
  threads: StoredThread[]; currentThreadId: string; runningThreads: Record<string, boolean>;
  runs: Record<string, Run>; isHydrated: boolean; selectedModel: string;
  models: {id: string; name: string}[]; error: string | null;
  setModel: (model: string) => void;
  setRunning: (id: string, running: boolean) => void;
  upsertThread: (thread: StoredThread) => void;
  setMessages: (id: string, messages: (StoredMessage | MessageResponse)[]) => void;
  snapshot: (run: Run) => void;
}
export const normalizeMessage = (m: StoredMessage | MessageResponse): StoredMessage => ({...m, createdAt: new Date(m.createdAt)});
export const useThreadStore = create<State>((set) => ({
  threads: [], currentThreadId: "", runningThreads: {}, runs: {}, isHydrated: false,
  selectedModel: "default", models: [], error: null,
  setModel: (selectedModel) => set({selectedModel}),
  setRunning: (id, running) => set(s => ({runningThreads: {...s.runningThreads, [id]: running}})),
  upsertThread: (thread) => set(s => ({threads: s.threads.some(t => t.id === thread.id)
    ? s.threads.map(t => t.id === thread.id ? {...t, ...thread} : t) : [thread, ...s.threads]})),
  setMessages: (id, messages) => set(s => ({threads: s.threads.map(t => t.id === id ? {...t, messages: messages.map(normalizeMessage)} : t)})),
  snapshot: (run) => set(s => ({
    runs: {...s.runs, [run.thread_id]: run},
    runningThreads: {...s.runningThreads, [run.thread_id]: ["queued", "running"].includes(run.status)},
    threads: s.threads.map(t => t.id !== run.thread_id || !run.message ? t : {...t,
      messages: t.messages.some(m => m.id === run.message!.id)
        ? t.messages.map(m => m.id === run.message!.id ? normalizeMessage(run.message!) : m)
        : [...t.messages, normalizeMessage(run.message)]}),
  })),
}));
