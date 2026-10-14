/** Decode fragmented UTF-8 SSE frames. A terminal event is required for success. */
export async function readEvents(response: Response, onEvent: (event: Record<string, unknown>) => void) {
  if (!response.body) throw new Error("Missing stream body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", terminal = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // Normalize only complete lines, including CRLF split across network reads.
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame.split(/\r?\n/).filter(l => l.startsWith("data:")).map(l => l.slice(5).trimStart()).join("\n");
        if (!data) continue;
        const event = JSON.parse(data) as Record<string, unknown>;
        onEvent(event);
        if (event.type === "terminal") { terminal = true; return; }
      }
      if (done) break;
    }
    if (!terminal) throw new Error("Stream interrupted. Reconnect to recover the saved answer.");
  } finally { await reader.cancel(); reader.releaseLock(); }
}
