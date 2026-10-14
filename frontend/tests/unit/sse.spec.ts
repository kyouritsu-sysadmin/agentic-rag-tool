import {test,expect} from "@playwright/test";
import {readEvents} from "../../src/lib/sse";
test("fragmented UTF-8 and CRLF frames survive one-byte chunks",async()=>{
  const bytes=new TextEncoder().encode('data: {"type":"snapshot","text":"日本語"}\r\n\r\ndata: {"type":"terminal"}\n\n');
  const stream=new ReadableStream({start(c){for(const b of bytes)c.enqueue(Uint8Array.of(b));c.close();}});
  const events:Record<string,unknown>[]=[];
  await readEvents(new Response(stream),e=>events.push(e));
  expect(events).toEqual([{type:"snapshot",text:"日本語"},{type:"terminal"}]);
});
test("premature EOF remains an error",async()=>{
  await expect(readEvents(new Response('data: {"type":"snapshot"}\n\n'),()=>{})).rejects.toThrow("Stream interrupted");
});
