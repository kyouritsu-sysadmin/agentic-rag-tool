import { chatApi } from "./api";
import type { ThreadResponse, MessageResponse, ThreadPatch } from "@/lib/contracts/api";
import { readEvents } from "@/lib/sse";
import { useThreadStore, type Run } from "./store";
const submitting = new Set<string>();
const submissionVersions = new Map<string, number>();
const historyVersions = new Map<string, number>();
const watching = new Map<string, Promise<void>>();
const cancelRequested = new Set<string>();
const pending = new Map<string, {text: string; parent: string | null | undefined; key: string}>();
export function report(error: unknown) { useThreadStore.setState({error: error instanceof Error ? error.message : "Request failed"}); }
export async function refreshThreads() {
  const threads: ThreadResponse[] = [];
  let offset: number | null = 0;
  while (offset !== null) {
    const result = await chatApi.listThreads(offset);
    threads.push(...result.threads); offset = result.next_offset;
  }
  useThreadStore.setState(s => ({threads: threads.map(t => ({...t, title: t.title ?? undefined, createdAt: new Date(t.createdAt),
    messages: s.threads.find(old => old.id === t.id)?.messages ?? []})), isHydrated: true}));
}
export async function newThread() {
  const selected = useThreadStore.getState().currentThreadId;
  const thread = await chatApi.createThread();
  useThreadStore.getState().upsertThread({...thread, title: thread.title ?? undefined, messages: [], createdAt: new Date(thread.createdAt)});
  if (useThreadStore.getState().currentThreadId === selected) useThreadStore.setState({currentThreadId: thread.id});
  return thread.id;
}
export async function loadHistory(id: string) {
  const version = (historyVersions.get(id) ?? 0) + 1;
  historyVersions.set(id, version);
  const submission = submissionVersions.get(id);
  const observedRun = useThreadStore.getState().runs[id];
  let head: string | null = null;
  let messages: MessageResponse[] = [];
  let run: Run | null = null;
  do {
    const result = await chatApi.history(id, head);
    messages = [...result.messages, ...messages]; head = result.older_head_id; run = result.active_run;
  } while (head);
  // A newer submission, history load, or stream snapshot takes precedence.
  if (historyVersions.get(id) !== version || submissionVersions.get(id) !== submission ||
      useThreadStore.getState().runs[id] !== observedRun) return;
  useThreadStore.getState().setMessages(id, messages);
  if (run) { useThreadStore.getState().snapshot(run); void watchRun(run).catch(report); }
  else {
    // History is authoritative after reconnect, even if the run-status GET failed.
    const message = observedRun && messages.find(m => m.id === observedRun.assistant_message_id);
    if (message?.status && !["queued", "running"].includes(message.status)) {
      useThreadStore.getState().snapshot({...observedRun, status: message.status, message});
    } else {
      useThreadStore.setState(s => {
        const runs = {...s.runs}; delete runs[id];
        return {runs, runningThreads: {...s.runningThreads, [id]: false}};
      });
    }
  }
}
export function watchRun(run: Run): Promise<void> {
  const existing = watching.get(run.id); if (existing) return existing;
  const work = (async () => {
    await readEvents(await chatApi.events(run.id), event => {
      if (event.type === "snapshot") useThreadStore.getState().snapshot(event as unknown as Run);
      if (event.type === "terminal" && event.status !== "completed") report(event.error || `Generation ${event.status}`);
    });
  })().catch(async error => {
    // EOF is not successful completion. Recover durable status and offer reconnect.
    try { useThreadStore.getState().snapshot(await chatApi.run(run.id)); } catch { /* Preserve existing answer. */ }
    throw error;
  }).finally(() => watching.delete(run.id));
  watching.set(run.id, work); return work;
}
export async function send(text: string, parent?: string | null) {
  const admission = useThreadStore.getState().currentThreadId;
  if (submitting.has("") || submitting.has(admission) || useThreadStore.getState().runningThreads[admission])
    throw new Error("Generation is already active");
  // Reserve the blank composer synchronously, before thread creation can yield.
  submitting.add(admission);
  useThreadStore.getState().setRunning(admission, true);
  let id = admission;
  try {
    if (!id) id = await newThread();
    submitting.add(id);
    if (!admission) {
      submitting.delete("");
      useThreadStore.getState().setRunning("", false);
      if (cancelRequested.delete("")) cancelRequested.add(id);
    }
    submissionVersions.set(id, (submissionVersions.get(id) ?? 0) + 1);
    const store = useThreadStore.getState();
    store.setRunning(id, true);
    const previous = pending.get(id);
    const request = previous && previous.text === text && previous.parent === parent ? previous : {text, parent, key: crypto.randomUUID()};
    pending.set(id, request);
    const run = await chatApi.submit(id, {
      text, ...(parent !== undefined ? {parent_id: parent} : {}), model_id: store.selectedModel, idempotency_key: request.key,
    });
    pending.delete(id);
    store.snapshot(run);
    if (cancelRequested.delete(id)) await cancelCurrent(id);
    await loadHistory(id);
    await refreshThreads();
    await watchRun(run);
  } catch (error) {
    // If submission acknowledgement was lost, reuse the same key when retried.
    if (!useThreadStore.getState().runs[id] || !["queued","running"].includes(useThreadStore.getState().runs[id].status)) useThreadStore.getState().setRunning(id, false);
    throw error;
  } finally {
    submitting.delete(id);
    if (!id) {
      useThreadStore.getState().setRunning("", false);
      cancelRequested.delete("");
    }
  }
}
export async function changeThread(id: string, patch: ThreadPatch) {
  await chatApi.patchThread(id, patch);
  await refreshThreads();
}

export async function cancelCurrent(id: string) {
  const run = useThreadStore.getState().runs[id];
  if (run && ["queued", "running"].includes(run.status)) {
    useThreadStore.getState().snapshot(await chatApi.cancel(run.id));
  } else if (useThreadStore.getState().runningThreads[id]) cancelRequested.add(id);
}

export async function bootstrapChat() {
  const catalog = await chatApi.models();
  await refreshThreads();
  useThreadStore.setState({models: catalog.models, error: null});
  const id = useThreadStore.getState().threads.find(t => t.status === "regular")?.id;
  if (id) { useThreadStore.setState({currentThreadId: id}); await loadHistory(id); }
}
