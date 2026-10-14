"use client";
import type { ReactNode } from "react";
import { AuthGate } from "@/features/auth/components/auth-gate";
import { ChatRuntimeProvider } from "@/features/chat/runtime-provider";
import { bootstrapChat } from "@/features/chat/actions";

export function ApplicationProviders({children}: {children: ReactNode}) {
  return <AuthGate onConnect={bootstrapChat}><ChatRuntimeProvider>{children}</ChatRuntimeProvider></AuthGate>;
}
