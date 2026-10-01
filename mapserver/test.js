"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { createApp, MapStore } = require("./server");

function sampleChunk(cx, cz) {
  const cells = [];
  for (let i = 0; i < 256; i++) {
    const y = 64 + ((i * 7) % 9);
    cells.push([y, 1, y - 1, 0, y - 2, 0, y - 3, 0]);
  }
  return {
    v: 1,
    dim: "overworld",
    cx: cx,
    cz: cz,
    depth: 4,
    palette: ["minecraft:stone", "minecraft:grass_block"],
    cells: cells,
  };
}

async function req(base, pathname, options = {}) {
  const res = await fetch(base + pathname, options);
  const text = await res.text();
  let body = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }
  return { status: res.status, body: body };
}

async function main() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "mapserver-"));
  const dataFile = path.join(tmpDir, "chunks.ndjson");

  const app = createApp({
    dataFile: dataFile,
    apiKey: "secret",
    publicDir: path.join(__dirname, "public"),
  });

  await new Promise((resolve) => app.server.listen(0, "127.0.0.1", resolve));
  const base = "http://127.0.0.1:" + app.server.address().port;

  const payload = sampleChunk(0, 0);

  // 1. ecriture sans cle -> refuse
  let r = await req(base, "/api/chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  assert.strictEqual(r.status, 401, "ecriture sans cle doit etre refusee");

  // 2. mauvaise cle -> refuse
  r = await req(base, "/api/chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Api-Key": "nope" },
    body: JSON.stringify(payload),
  });
  assert.strictEqual(r.status, 401, "mauvaise cle doit etre refusee");

  // 3. bonne cle -> accepte
  r = await req(base, "/api/chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Api-Key": "secret" },
    body: JSON.stringify(payload),
  });
  assert.strictEqual(r.status, 200, "ecriture acceptee");
  assert.strictEqual(r.body.ok, true);

  // 4. payload invalide -> 422
  r = await req(base, "/api/chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Api-Key": "secret" },
    body: JSON.stringify({ dim: "overworld", cx: 1 }),
  });
  assert.strictEqual(r.status, 422, "payload invalide refuse");

  // 5. statuts
  r = await req(base, "/api/status");
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.body.chunks, 1, "un chunk en memoire");
  assert.strictEqual(r.body.tile_size, 8);
  assert.deepStrictEqual(r.body.dimensions, ["overworld"]);

  // 6. meta
  r = await req(base, "/api/meta?dim=overworld");
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.body.count, 1);
  assert.ok(r.body.y_max >= r.body.y_min, "bornes Y coherentes");

  // 7. tile
  r = await req(base, "/api/tile/overworld/0/0");
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.body.chunks.length, 1);

  // 8. tile absente -> vide
  r = await req(base, "/api/tile/overworld/99/99");
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.body.chunks.length, 0);

  // 9. chunk individuel
  r = await req(base, "/api/chunk/overworld/0/0");
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.body.cx, 0);

  // 10. plage
  r = await req(base, "/api/chunks?dim=overworld&cx0=-1&cz0=-1&cx1=1&cz1=1");
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.body.chunks.length, 1);

  // 11. statique
  r = await req(base, "/");
  assert.strictEqual(r.status, 200, "index servi");
  assert.ok(String(r.body).includes("<!DOCTYPE html>"));

  r = await req(base, "/styles.css");
  assert.strictEqual(r.status, 200);

  // 12. traversal refuse
  r = await req(base, "/../server.js");
  assert.ok(r.status === 403 || r.status === 404, "traversal bloque, got " + r.status);

  // 13. methode inconnue
  r = await req(base, "/api/status", { method: "DELETE" });
  assert.strictEqual(r.status, 405);

  // 14. persistance
  await app.store.close();
  app.server.close();

  const reloaded = new MapStore({ dataFile: dataFile });
  assert.strictEqual(reloaded.chunks.size, 1, "reload depuis ndjson");
  assert.ok(reloaded.get("overworld", 0, 0), "chunk relue");
  await reloaded.close();
  fs.rmSync(tmpDir, { recursive: true, force: true });

  console.log("OK - 14 assertions passees");
}

main().catch((err) => {
  console.error("ECHEC :", err.message);
  process.exitCode = 1;
});
