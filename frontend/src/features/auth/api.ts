import { api, setAccessToken } from "@/lib/api-client";
import type { PrincipalResponse } from "@/lib/contracts/api";

export async function authenticate(token: string) {
  setAccessToken(token);
  return api<PrincipalResponse>("/v1/me");
}
