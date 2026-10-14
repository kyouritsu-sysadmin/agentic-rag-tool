"use client";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { authenticate } from "../api";

export function AuthGate({children, onConnect}: {children: ReactNode; onConnect: () => Promise<void>}) {
  const [token, setToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connect = useCallback(async (value: string) => {
    try {
      await authenticate(value);
      await onConnect();
      sessionStorage.setItem("rag-access-token", value);
      setError(null);
      setConnected(true);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Connection failed");
    }
  }, [onConnect]);
  useEffect(() => {
    const saved = sessionStorage.getItem("rag-access-token");
    if (saved) queueMicrotask(() => void connect(saved));
  }, [connect]);
  if (connected) return children;
  return <main className="m-auto max-w-md space-y-4 p-8"><h1 className="text-xl font-semibold">共立 RAG</h1>
    <p>Enter your assigned access token to open your conversations.</p>
    <form onSubmit={e => {e.preventDefault(); void connect(token);}} className="space-y-4">
      <label className="block">Access token<input aria-label="Access token" type="password" required value={token} onChange={e=>setToken(e.target.value)} className="block w-full rounded border p-2" /></label>
      <button className="rounded bg-primary px-4 py-2 text-primary-foreground">Connect</button>
    </form>{error && <p role="alert">{error}</p>}</main>;
}
