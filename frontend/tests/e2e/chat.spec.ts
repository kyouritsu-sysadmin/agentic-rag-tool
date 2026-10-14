import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
const token = "browser-admin-token-00001";
test("authenticated source → chat → refresh → branch → ownership", async ({page, request}) => {
  const response = await request.post("http://127.0.0.1:8018/v1/documents", {headers:{Authorization:`Bearer ${token}`},multipart:{
    metadata:JSON.stringify({company:"A",dept:"sales",year:2025,month:1,import_key:`browser-${Date.now()}`}),
    file:{name:"browser-report.txt",mimeType:"text/plain",buffer:Buffer.from("Sales revenue increased. ".repeat(40))},
  }});
  expect(response.status()).toBe(202);
  const job = await response.json();
  await expect.poll(async () => (await (await request.get(`http://127.0.0.1:8018/v1/jobs/${job.job_id}`,{headers:{Authorization:`Bearer ${token}`}})).json()).status).toBe("completed");
  await page.goto("/");
  await page.getByLabel("Access token").fill(token);
  await page.getByRole("button",{name:"Connect",exact:true}).click();
  await expect(page.getByText("Sign out",{exact:true})).toBeVisible();
  // Repeated runs may find existing chats in the disposable database.
  await page.getByRole("button",{name:"New Thread",exact:true}).click();
  const input = page.locator("textarea").first();
  await input.fill("2025年1月 Sales revenue");
  const initialResponsePromise = page.waitForResponse(response =>
    response.request().method() === "POST" && /\/v1\/threads\/[^/]+\/messages$/.test(response.url()));
  await input.press("Enter");
  const initialResponse = await initialResponsePromise;
  expect(initialResponse.status()).toBe(202);
  const initialRun = await initialResponse.json();
  await expect(page.locator('[data-role="assistant"]').getByText("[TEST PROVIDER]",{exact:false}).first()).toBeVisible({timeout:15000});
  await expect(page.getByRole("button",{name:"browser-report.txt"}).first()).toBeVisible();
  await expect(page.getByRole("button",{name:"Stop generating"})).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button",{name:"browser-report.txt"}).first()).toBeVisible({timeout:10000});
  // Regeneration and editing are acknowledged backend branches, not deleted history.
  await page.getByRole("button", {name:"Refresh", exact:true}).last().click();
  await expect(page.getByRole("button",{name:"Stop generating"})).toBeVisible();
  await page.getByRole("button",{name:"Stop generating"}).click();
  await expect(page.getByRole("button",{name:"Stop generating"})).toHaveCount(0);
  await page.locator('[data-role="user"]').last().hover();
  await page.getByRole("button",{name:"Edit",exact:true}).last().click();
  await page.locator(".aui-edit-composer-input").fill("2025年1月 Sales revenue edited");
  const editResponsePromise = page.waitForResponse(response =>
    response.request().method() === "POST" && /\/v1\/threads\/[^/]+\/messages$/.test(response.url()));
  await page.getByRole("button",{name:"Update",exact:true}).click();
  const editResponse = await editResponsePromise;
  expect(editResponse.status()).toBe(202);
  const editRun = await editResponse.json();
  await expect.poll(async () => (await (await request.get(`http://127.0.0.1:8018/v1/runs/${editRun.id}`,{headers:{Authorization:`Bearer ${token}`}})).json()).status).toBe("completed");
  await expect(page.getByRole("button",{name:"Stop generating"})).toHaveCount(0,{timeout:10000});
  await expect(page.getByText("2025年1月 Sales revenue edited",{exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"browser-report.txt"}).first()).toBeVisible();
  const downloadPromise=page.waitForEvent("download");
  await page.getByRole("button",{name:"browser-report.txt"}).first().click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("browser-report.txt");
  expect(await readFile((await download.path())!, "utf8")).toBe("Sales revenue increased. ".repeat(40));
  await expect(page.getByText("[TEST] Fixture model",{exact:true})).toBeVisible();
  const threads = await (await request.get("http://127.0.0.1:8018/v1/threads",{headers:{Authorization:`Bearer ${token}`}})).json();
  const thread=threads.threads[0];
  const runResponse=await request.post(`http://127.0.0.1:8018/v1/threads/${thread.id}/messages`,{headers:{Authorization:`Bearer ${token}`},data:{text:"Sales revenue",parent_id:null,idempotency_key:`branch-${Date.now()}`}});
  expect(runResponse.status()).toBe(202);
  const run=await runResponse.json();
  await expect.poll(async()=>(await(await request.get(`http://127.0.0.1:8018/v1/runs/${run.id}`,{headers:{Authorization:`Bearer ${token}`}})).json()).status).toBe("completed");
  await page.reload();
  await expect(page.getByLabel("Saved branches")).toBeEnabled();
  await page.getByLabel("Saved branches").focus();
  await expect(page.getByLabel("Saved branches").locator("option")).toHaveCount(5);
  await page.getByLabel("Saved branches").selectOption(initialRun.assistant_message_id);
  await expect(page.getByText("2025年1月 Sales revenue",{exact:true}).last()).toBeVisible();
  await expect(page.getByText("2025年1月 Sales revenue edited",{exact:true})).toHaveCount(0);
  await expect.poll(async () => {
    const result = await (await request.get("http://127.0.0.1:8018/v1/threads",{headers:{Authorization:`Bearer ${token}`}})).json();
    return result.threads.find((item: {id: string}) => item.id === thread.id).head_id;
  }).toBe(initialRun.assistant_message_id);
  expect((await request.get(`http://127.0.0.1:8018/v1/threads/${thread.id}/messages`,{headers:{Authorization:"Bearer browser-reader-token-0002"}})).status()).toBe(404);
  expect((await request.get("http://127.0.0.1:3018/api/threads")).status()).toBe(404);
  await page.screenshot({path:"test-results/integrated-chat.png",fullPage:true});

  const sidebar = page.getByRole("complementary",{name:"Chat sidebar"});
  const row = sidebar.locator(".aui-thread-list-item").filter({hasText:thread.title}).first();
  await row.hover();
  await row.getByRole("button",{name:"More options",exact:true}).click();
  await page.getByRole("menuitem",{name:"Archive",exact:true}).click();
  await sidebar.locator("summary").filter({hasText:"Archived"}).click();
  await sidebar.getByRole("button",{name:"Restore",exact:true}).click();
  await row.hover();
  await row.getByRole("button",{name:"More options",exact:true}).click();
  await page.getByRole("menuitem",{name:"Delete",exact:true}).click();
  await expect.poll(async () => (await request.get(`http://127.0.0.1:8018/v1/threads/${thread.id}/messages`,{headers:{Authorization:`Bearer ${token}`}})).status()).toBe(404);
});

test("invalid token, sidebar on desktop/mobile, and sign out", async ({page}) => {
  await page.goto("/");
  await page.getByLabel("Access token").fill("invalid-simulation-token");
  await page.getByRole("button",{name:"Connect",exact:true}).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("A valid access token is required");
  await page.getByLabel("Access token").fill(token);
  await page.getByRole("button",{name:"Connect",exact:true}).click();
  const sidebar = page.getByRole("complementary",{name:"Chat sidebar"});
  await expect(sidebar.getByRole("button",{name:"Sign out",exact:true})).toBeVisible();
  await sidebar.getByRole("button",{name:"Close sidebar",exact:true}).click();
  await sidebar.getByRole("button",{name:"Open sidebar",exact:true}).click();
  await expect(sidebar.getByLabel("Saved branches")).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole("button",{name:"Open sidebar",exact:true}).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("button",{name:"New Thread",exact:true})).toBeVisible();
  await expect(drawer.getByLabel("Saved branches")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button",{name:"Open sidebar",exact:true})).toBeFocused();
  await page.getByRole("button",{name:"Open sidebar",exact:true}).click();
  await drawer.getByRole("button",{name:"Sign out",exact:true}).click();
  await expect(page.getByLabel("Access token")).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("rag-access-token"))).toBeNull();
  await page.reload();
  await expect(page.getByLabel("Access token")).toBeVisible();
});
