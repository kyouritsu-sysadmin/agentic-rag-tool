import { test, expect } from "@playwright/test";
import { chatApi } from "../../src/features/chat/api";
const originalFetch = globalThis.fetch;
test.afterEach(() => {globalThis.fetch = originalFetch;});
test("branch selection includes answers beyond the first 100", async () => {
  const offsets: string[] = [];
  globalThis.fetch = async input => {
    const offset = new URL(String(input)).searchParams.get("offset")!;
    offsets.push(offset);
    return Response.json({head_id:"latest", branches: offset === "0"
      ? Array.from({length:100}, (_, i) => ({id:`answer-${i}`, preview:"answer", status:"completed"}))
      : [{id:"oldest-answer", preview:"older branch", status:"completed"}], next_offset:offset === "0" ? 100 : null});
  };
  const result = await chatApi.branches("thread");
  expect(offsets).toEqual(["0", "100"]);
  expect(result.branches).toHaveLength(101);
  expect(result.branches.at(-1)?.id).toBe("oldest-answer");
});
test("invalid pagination cannot keep the selector fetching indefinitely", async () => {
  globalThis.fetch = async () => Response.json({head_id:null, branches:[], next_offset:0});
  await expect(chatApi.branches("thread")).rejects.toThrow("Invalid branch pagination");
});
