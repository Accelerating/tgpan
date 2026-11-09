import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/lib/transfers.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
}).outputText;
const { transferSummary } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
const task = (overrides = {}) => ({
  id: "remote",
  state: "sending",
  size: 100,
  received: 100,
  stored: 20,
  sending_bytes: 10,
  ...overrides,
});
const job = (overrides = {}) => ({
  file: { size: 100 },
  state: "uploading",
  received: 60,
  ...overrides,
});

test("merges local and server records, keeping both upload phases separate", () => {
  assert.deepEqual(
    transferSummary(
      [job({ taskId: "remote", received: 90 })],
      [task({ received: 80 })],
    ),
    {
      count: 1,
      attention: false,
      received: 90,
      stored: 30,
    },
  );
});

test("weights queued files by bytes and excludes ended tasks", () => {
  const result = transferSummary(
    [job({ file: { size: 300 }, state: "queued", received: 0 })],
    [
      task(),
      task({ id: "done", state: "complete" }),
      task({ id: "cancelled", state: "cancelled" }),
      task({ id: "expired", state: "expired" }),
    ],
  );
  assert.equal(result.count, 2);
  assert.equal(result.received, 25);
  assert.equal(result.stored, 7.5);
});

test("keeps paused and failed uploads discoverable, without resurrecting cancelled ones", () => {
  assert.equal(transferSummary([job({ state: "paused" })], []).attention, true);
  assert.equal(transferSummary([], [task({ state: "error" })]).count, 1);
  assert.equal(
    transferSummary(
      [job({ taskId: "remote", state: "paused" })],
      [task({ state: "cancelled" })],
    ).count,
    0,
  );
  assert.deepEqual(transferSummary([], []), {
    count: 0,
    attention: false,
    received: 0,
    stored: 0,
  });
});
