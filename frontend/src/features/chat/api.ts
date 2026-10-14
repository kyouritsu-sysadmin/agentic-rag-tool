import { api, apiFetch } from "@/lib/api-client";
import type { ThreadResponse, ThreadPage, ThreadPatch, SubmitMessage, HistoryResponse, RunResponse, RunDetail, BranchPage, ModelPage } from "@/lib/contracts/api";

export const chatApi = {
  listThreads: (offset: number) => api<ThreadPage>(`/v1/threads?offset=${offset}`),
  createThread: () => api<ThreadResponse>("/v1/threads", {method:"POST", body: JSON.stringify({})}),
  history: (id: string, head: string | null) => api<HistoryResponse>(`/v1/threads/${id}/messages?limit=200${head ? `&head_id=${encodeURIComponent(head)}` : ""}`),
  submit: (id: string, body: SubmitMessage) => api<RunResponse>(`/v1/threads/${id}/messages`, {method:"POST", body:JSON.stringify(body)}),
  run: (id: string) => api<RunDetail>(`/v1/runs/${id}`),
  events: (id: string) => apiFetch(`/v1/runs/${id}/events`),
  cancel: (id: string) => api<RunDetail>(`/v1/runs/${id}/cancel`, {method:"POST"}),
  patchThread: (id: string, patch: ThreadPatch) => api<ThreadResponse>(`/v1/threads/${id}`, {method:"PATCH", body:JSON.stringify(patch)}),
  deleteThread: (id: string) => api<void>(`/v1/threads/${id}`, {method:"DELETE"}),
  branches: async (id: string): Promise<BranchPage> => {
    const branches: BranchPage["branches"] = [];
    let offset: number | null = 0;
    let head_id: string | null = null;
    while (offset !== null) {
      const page: BranchPage = await api<BranchPage>(`/v1/threads/${id}/branches?offset=${offset}`);
      branches.push(...page.branches);
      head_id = page.head_id;
      if (page.next_offset !== null && page.next_offset <= offset) throw new Error("Invalid branch pagination");
      offset = page.next_offset;
    }
    return {branches, head_id, next_offset: null};
  },
  models: () => api<ModelPage>("/v1/models"),
};
