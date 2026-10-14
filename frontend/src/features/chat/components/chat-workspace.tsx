"use client";

import { useState } from "react";
import { Thread } from "@/features/chat/components/thread";
import { ThreadList } from "@/features/chat/components/thread-list";
import { BranchSelector } from "@/features/chat/components/branch-selector";
import { SignOutButton } from "@/features/auth/components/sign-out-button";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

function SidebarContent() {
  return (
    <>
      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto p-3">
        <ThreadList />
      </nav>
      <div className="shrink-0 space-y-3 border-t p-3">
        <BranchSelector />
        <SignOutButton />
      </div>
    </>
  );
}

export default function ChatWorkspace() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <main className="flex min-h-0 flex-1 overflow-hidden bg-background">
      {/* ── Sidebar ── */}
      <aside
        aria-label="Chat sidebar"
        className={`hidden md:flex flex-col border-r bg-muted/20 overflow-hidden transition-all duration-300 ease-in-out shrink-0 ${
          sidebarOpen ? "w-80" : "w-12"
        }`}
      >
        <div
          className={`flex items-center h-12 border-b shrink-0 gap-2 ${
            sidebarOpen ? "px-4 justify-between" : "px-2 justify-center"
          }`}
        >
          {sidebarOpen && (
            <span className="text-sm font-semibold text-foreground/70 tracking-wide truncate">
              共立 RAG
            </span>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            aria-expanded={sidebarOpen}
          >
            {sidebarOpen ? (
              <PanelLeftClose className="size-4" />
            ) : (
              <PanelLeftOpen className="size-4" />
            )}
          </Button>
        </div>
        {sidebarOpen && <SidebarContent />}
      </aside>

      {/* ── Chat area ── */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3 md:hidden">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open sidebar">
                <PanelLeftOpen className="size-4" />
              </Button>
            </DialogTrigger>
            <DialogContent
              aria-describedby={undefined}
              className="top-0 left-0 flex h-dvh w-80 max-w-[calc(100vw-3rem)] translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-r bg-background p-0 sm:max-w-80"
            >
              <div className="flex h-12 shrink-0 items-center border-b px-4">
                <DialogTitle className="text-sm">共立 RAG</DialogTitle>
              </div>
              <SidebarContent />
            </DialogContent>
          </Dialog>
          <span className="text-sm font-semibold">共立 RAG</span>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <Thread />
        </div>
      </div>
    </main>
  );
}
