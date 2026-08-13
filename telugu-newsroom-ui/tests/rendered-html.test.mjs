import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the MediaOps newsroom shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, />mediaops</i);
  assert.match(html, /AI NEWSROOM/);
  assert.match(html, /Run workflow/);
  assert.match(html, /Long video → topic-wise newsroom packages/);
  assert.match(html, /PIPELINE DISCONNECTED/);
  assert.doesNotMatch(html, /Your site is taking shape|starter loading/i);
});

test("keeps real pipeline operations in the client workspace", async () => {
  const [page, layout, css] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /MediaOps — Visual AI Newsroom/);
  assert.match(page, /\/api\/jobs\/upload/);
  assert.match(page, /\/package/);
  assert.match(page, /XMLHttpRequest/);
  assert.match(page, /<video className="real-video"/);
  assert.match(page, /Render MP4 \+ MP3 \+ transcript/);
  assert.match(css, /\.upload-dialog/);
  assert.match(css, /\.package-downloads/);
  assert.doesNotMatch(page, /Math\.random|Date\.now/);
});
