"use client";
import { type ReactNode } from "react";
import { AssistantRuntimeProvider, useExternalStoreRuntime, type ExternalStoreAdapter } from "@assistant-ui/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useThreadStore, type StoredMessage } from "@/features/chat/store";
import { chatApi } from "./api";
import { report, refreshThreads, loadHistory, send, changeThread, cancelCurrent } from "@/features/chat/actions";

export function ChatRuntimeProvider({children}: {children: ReactNode}) {
  const store = useThreadStore();
  const safe = async (action: () => Promise<unknown>) => { try { await action(); } catch (error) { report(error); } };
  const thread = store.threads.find(t => t.id === store.currentThreadId);
  const textOf = (message: {content: readonly {type: string; text?: string}[]}) => message.content.filter(c => c.type === "text").map(c => c.text ?? "").join("");
  const adapter: ExternalStoreAdapter<StoredMessage> = {
    isRunning: !!store.runningThreads[store.currentThreadId], messages: thread?.messages ?? [],
    convertMessage: m => ({id: m.id, role: m.role, content: [{type:"text", text:m.text}], createdAt:m.createdAt,
      ...(m.role === "assistant" ? {status: ["queued","running"].includes(m.status ?? "") ? {type:"running" as const}
        : m.status === "completed" ? {type:"complete" as const, reason:"stop" as const}
        : {type:"incomplete" as const, reason: m.status === "cancelled" ? "cancelled" as const : "error" as const}}
        : {attachments: []})}),
    onNew: m => safe(() => send(textOf(m))),
    onEdit: m => safe(() => send(textOf(m), m.parentId ?? null)),
    onReload: parentId => safe(async () => {
      const user = thread?.messages.find(m => m.id === parentId && m.role === "user");
      if (!user) throw new Error("Cannot find the message to regenerate");
      await send(user.text, user.parent_id ?? null);
    }),
    onCancel: () => safe(async () => {
      await cancelCurrent(store.currentThreadId);
    }),
    adapters: {threadList: {
      threadId: store.currentThreadId || undefined, isLoading: !store.isHydrated,
      threads: store.threads.filter(t => t.status === "regular").map(t => ({id:t.id, title:t.title, status:"regular" as const})),
      archivedThreads: store.threads.filter(t => t.status === "archived").map(t => ({id:t.id, title:t.title, status:"archived" as const})),
      onSwitchToNewThread: () => safe(async () => { useThreadStore.setState({currentThreadId:""}); }),
      onSwitchToThread: id => safe(async () => { useThreadStore.setState({currentThreadId:id}); await loadHistory(id); }),
      onArchive: id => safe(async () => { await changeThread(id,{status:"archived"}); if (id===store.currentThreadId) useThreadStore.setState({currentThreadId:""}); }),
      onUnarchive: id => safe(() => changeThread(id,{status:"regular"})),
      onRename: (id, title) => safe(() => changeThread(id,{title})),
      onDelete: id => safe(async () => { await chatApi.deleteThread(id); await refreshThreads(); if(id===store.currentThreadId) useThreadStore.setState({currentThreadId:""}); }),
    }},
  };
  const runtime = useExternalStoreRuntime(adapter);
  return <AssistantRuntimeProvider runtime={runtime}><TooltipProvider>
    <div className="flex h-dvh min-h-0 flex-col overflow-hidden">
      {store.error && <div role="alert" className="shrink-0 border-b bg-red-50 p-2 text-sm text-red-900">{store.error} <button onClick={()=>void safe(async()=>{await refreshThreads(); if(store.currentThreadId) await loadHistory(store.currentThreadId); useThreadStore.setState({error:null});})}>Reconnect</button></div>}
      {children}
    </div>
  </TooltipProvider></AssistantRuntimeProvider>;
}
