import { API_URL } from "./config";
let accessToken = "";
export function setAccessToken(token: string) { accessToken = token; }
export async function apiFetch(path: string, init: RequestInit = {}) {
  const response = await fetch(API_URL + path, { ...init, cache: "no-store", headers: {
    ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
    ...init.headers, Authorization: `Bearer ${accessToken}`,
  }});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return response;
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  return response.status === 204 ? undefined as T : response.json();
}
export async function downloadSource(path: string, name: string) {
  // Only backend-relative source paths are accepted; never send tokens to arbitrary URLs.
  if (!/^\/v1\/documents\/[^/]+\/versions\/[^/]+\/source$/.test(path)) throw new Error("Invalid source link");
  const response = await apiFetch(path);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
