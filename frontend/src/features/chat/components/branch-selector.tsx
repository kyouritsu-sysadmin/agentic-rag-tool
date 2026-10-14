"use client";
import { useEffect, useState } from "react";
import { useThreadStore } from "../store";
import { chatApi } from "../api";
import { changeThread, loadHistory, report } from "../actions";
import type { Branch } from "@/lib/contracts/api";

export function BranchSelector() {
  const id = useThreadStore(s => s.currentThreadId);
  const running = useThreadStore(s => !!s.runningThreads[id]);
  const [loaded, setLoaded] = useState<{id: string; branches: Branch[]} | null>(null);
  useEffect(() => {
    let active = true;
    if (id && !running) void chatApi.branches(id).then(result => {
      if (active) setLoaded({id, branches: result.branches});
    }).catch(error => { if (active) report(error); });
    return () => { active = false; };
  }, [id, running]);
  const branches = loaded?.id === id ? loaded.branches : [];
  return <label className="block space-y-2 text-xs font-medium text-muted-foreground">
    Saved branches
    <select className="block h-9 w-full min-w-0 truncate rounded-lg border bg-background px-2 text-sm font-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      aria-label="Saved branches" value="" disabled={!id || running || loaded?.id !== id}
      onChange={e => {
        if (e.target.value) void changeThread(id, {head_id: e.target.value}).then(() => loadHistory(id)).catch(report);
      }}>
      <option value="">Select an earlier answer</option>
      {branches.map((branch, index) => <option key={branch.id} value={branch.id}>{branch.preview || `Answer ${index + 1}`}</option>)}
    </select>
  </label>;
}
