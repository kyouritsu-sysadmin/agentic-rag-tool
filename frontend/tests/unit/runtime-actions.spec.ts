import { test, expect } from "@playwright/test";
import { loadHistory, send, watchRun } from "../../src/features/chat/actions";
import { useThreadStore, type Run, type StoredThread } from "../../src/features/chat/store";

const originalFetch = globalThis.fetch;
const thread = (id: string): StoredThread => ({id, title: "test", status: "regular", messages: [], createdAt: new Date()});
const run = (id: string, status = "running"): Run => ({id: `${id}-run`, thread_id: id, status,
  assistant_message_id: `${id}-answer`, message: {id: `${id}-answer`, role: "assistant", text: "answer", status, createdAt: new Date()}});
const json = (body: unknown, status = 200) => Response.json(body, {status});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => {resolve = r;});
  return {promise, resolve};
}
function completeRequests(id: string, input: string | URL | Request, init?: RequestInit) {
  const path = new URL(String(input)).pathname;
  if (path === "/v1/threads" && init?.method === "POST") return json(thread(id), 201);
  if (path.endsWith("/messages") && init?.method === "POST") return json(run(id), 202);
  if (path.endsWith("/messages")) return json({messages: [run(id, "completed").message], active_run: null, older_head_id: null});
  if (path === "/v1/threads") return json({threads: [thread(id)], next_offset: null});
  if (path.endsWith("/events")) return new Response(`data: ${JSON.stringify({type: "snapshot", ...run(id, "completed")})}\n\ndata: {"type":"terminal","status":"completed"}\n\n`);
  throw new Error(`Unexpected request ${path}`);
}

test.beforeEach(() => useThreadStore.setState(useThreadStore.getInitialState(), true));
test.afterEach(() => {globalThis.fetch = originalFetch;});

test("reconnect reconciles completion after both stream and run GET fail", async () => {
  const id = "reconnect";
  useThreadStore.getState().upsertThread(thread(id));
  useThreadStore.setState({currentThreadId: id});
  useThreadStore.getState().snapshot(run(id));
  globalThis.fetch = async () => {throw new Error("offline");};
  await expect(watchRun(run(id))).rejects.toThrow("offline");
  expect(useThreadStore.getState().runningThreads[id]).toBe(true);
  globalThis.fetch = async (input, init) => completeRequests(id, input, init);
  await loadHistory(id);
  expect(useThreadStore.getState().runningThreads[id]).toBe(false);
  expect(useThreadStore.getState().runs[id].status).toBe("completed");
  await send("next question");
  expect(useThreadStore.getState().runningThreads[id]).toBe(false);
});

test("an old history response cannot clear a newer running snapshot", async () => {
  const id = "snapshot-race";
  useThreadStore.getState().upsertThread(thread(id));
  const response = deferred<Response>();
  globalThis.fetch = () => response.promise;
  const loading = loadHistory(id);
  useThreadStore.getState().snapshot(run(id));
  response.resolve(json({messages: [], active_run: null, older_head_id: null}));
  await loading;
  expect(useThreadStore.getState().runningThreads[id]).toBe(true);
  expect(useThreadStore.getState().threads[0].messages).toHaveLength(1);
});

test("an old history response cannot clear a submission awaiting acknowledgement", async () => {
  const id = "submit-race";
  useThreadStore.getState().upsertThread(thread(id));
  useThreadStore.setState({currentThreadId: id});
  const history = deferred<Response>();
  const submitted = deferred<Response>();
  let firstHistory = true;
  globalThis.fetch = async (input, init) => {
    if (String(input).includes("/messages") && init?.method === "POST") return submitted.promise;
    if (String(input).includes("/messages") && firstHistory) {firstHistory = false; return history.promise;}
    return completeRequests(id, input, init);
  };
  const loading = loadHistory(id);
  const sending = send("question");
  history.resolve(json({messages: [], active_run: null, older_head_id: null}));
  await loading;
  expect(useThreadStore.getState().runningThreads[id]).toBe(true);
  submitted.resolve(json(run(id), 202));
  await sending;
});

test("overlapping first sends create one thread and submit one message", async () => {
  const id = "first-send";
  const created = deferred<Response>();
  let creates = 0, messages = 0;
  globalThis.fetch = async (input, init) => {
    if (new URL(String(input)).pathname === "/v1/threads" && init?.method === "POST") {creates++; return created.promise;}
    if (String(input).includes("/messages") && init?.method === "POST") messages++;
    return completeRequests(id, input, init);
  };
  const first = send("first");
  expect(useThreadStore.getState().runningThreads[""]).toBe(true);
  await expect(send("duplicate")).rejects.toThrow("already active");
  created.resolve(json(thread(id), 201));
  await first;
  expect({creates, messages}).toEqual({creates: 1, messages: 1});
  expect(useThreadStore.getState().runningThreads[""]).toBe(false);
});

test("failed initial thread creation releases admission for retry", async () => {
  globalThis.fetch = async () => json({detail: "offline"}, 503);
  await expect(send("question")).rejects.toThrow("offline");
  expect(useThreadStore.getState().runningThreads[""]).toBe(false);
  globalThis.fetch = async (input, init) => completeRequests("retry-create", input, init);
  await send("question");
  expect(useThreadStore.getState().currentThreadId).toBe("retry-create");
});

test("late thread creation does not replace a thread selected while waiting", async () => {
  const created = deferred<Response>();
  globalThis.fetch = async (input, init) => {
    if (new URL(String(input)).pathname === "/v1/threads" && init?.method === "POST") return created.promise;
    return completeRequests("late-create", input, init);
  };
  const sending = send("question");
  useThreadStore.setState({currentThreadId: "selected-elsewhere"});
  created.resolve(json(thread("late-create"), 201));
  await sending;
  expect(useThreadStore.getState().currentThreadId).toBe("selected-elsewhere");
});

test("finishing one chat cannot release another chat's initial-send reservation", async () => {
  const firstStream = deferred<Response>();
  const watchingFirst = deferred<void>();
  const secondCreated = deferred<Response>();
  let creates = 0;
  globalThis.fetch = async (input, init) => {
    const path = new URL(String(input)).pathname;
    if (path === "/v1/threads" && init?.method === "POST") {
      creates++;
      return creates === 1 ? json(thread("parallel-first"), 201) : secondCreated.promise;
    }
    if (path === "/v1/runs/parallel-first-run/events") {
      watchingFirst.resolve();
      return firstStream.promise;
    }
    const id = path.includes("parallel-first") || creates === 1 ? "parallel-first" : "parallel-second";
    return completeRequests(id, input, init);
  };
  const first = send("first chat");
  await watchingFirst.promise;
  useThreadStore.setState({currentThreadId: ""});
  const second = send("second chat");
  expect(creates).toBe(2);
  firstStream.resolve(completeRequests("parallel-first", "http://test/v1/runs/parallel-first-run/events"));
  await first;
  expect(useThreadStore.getState().runningThreads[""]).toBe(true);
  await expect(send("duplicate second")).rejects.toThrow("already active");
  secondCreated.resolve(json(thread("parallel-second"), 201));
  await second;
  expect(useThreadStore.getState().runningThreads[""]).toBe(false);
});
