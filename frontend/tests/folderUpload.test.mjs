import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = ts
  .transpileModule(
    readFileSync(
      new URL("../src/lib/folderUpload.ts", import.meta.url),
      "utf8",
    ),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ESNext,
      },
    },
  )
  .outputText.replace(
    'import { t } from "../i18n";',
    "const t = (text) => text;",
  )
  .replace(
    'import { api } from "./api";',
    "const api = (...args) => globalThis.uploadApi(...args);",
  );
const { selectedTree, droppedTree, enqueueTree } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

const fileEntry = (name) => ({
  name,
  isFile: true,
  isDirectory: false,
  file: (resolve) => queueMicrotask(() => resolve({ name })),
});
const directory = (name, batches) => ({
  name,
  isFile: false,
  isDirectory: true,
  createReader: () => {
    let index = 0;
    return {
      readEntries: (resolve) =>
        queueMicrotask(() => resolve(batches[index++] || [])),
    };
  },
});

test("folder picker preserves paths and resolves destinations before queuing files", async () => {
  const files = [
    { name: "a.txt", webkitRelativePath: "root/nested/a.txt" },
    { name: "b.txt", webkitRelativePath: "root/b.txt" },
    { name: "c.txt", webkitRelativePath: "root/nested/c.txt" },
  ];
  globalThis.uploadApi = async (path, method, body) => {
    assert.equal(path, "/files/folders/resolve");
    assert.equal(method, "POST");
    assert.equal(body.parent_id, "destination");
    assert.deepEqual(body.paths, ["root/nested", "root"]);
    return { "root/nested": "nested-id", root: "root-id" };
  };
  const jobs = [];
  await enqueueTree(selectedTree(files), "destination", (...args) =>
    jobs.push(args),
  );
  assert.deepEqual(jobs, [
    [[files[0], files[2]], "nested-id"],
    [[files[1]], "root-id"],
  ]);
});

test("drop captures entries synchronously and drains every directory batch, including empty folders", async () => {
  const root = directory("root", [
    [fileEntry("first.txt"), directory("empty", [])],
    [directory("nested", [[fileEntry("last.txt")]])],
  ]);
  let active = true;
  const transfer = {
    items: [root, fileEntry("loose.txt")].map((entry) => ({
      webkitGetAsEntry: () => {
        assert.ok(active, "entries must be captured during the drop event");
        return entry;
      },
    })),
    files: [],
  };
  const pending = droppedTree(transfer);
  active = false;
  const tree = await pending;
  assert.deepEqual(
    tree.files.map(({ file, directory }) => [file.name, directory]),
    [
      ["first.txt", "root"],
      ["last.txt", "root/nested"],
      ["loose.txt", ""],
    ],
  );
  globalThis.uploadApi = async (_path, _method, body) => {
    assert.deepEqual(body.paths, ["root", "root/nested"]);
    return { root: "root-id", "root/nested": "nested-id" };
  };
  await enqueueTree(tree, null, () => {});
});

test("empty directory trees are rejected before preparing folders or queuing files", async () => {
  const empty = directory("empty", [[directory("also-empty", [])]]);
  const tree = await droppedTree({
    items: [{ webkitGetAsEntry: () => empty }],
    files: [],
  });
  globalThis.uploadApi = () => assert.fail("empty folders must not be created");
  await assert.rejects(
    enqueueTree(tree, null, () =>
      assert.fail("empty folders must not be queued"),
    ),
  );
  await assert.rejects(
    enqueueTree(selectedTree([]), null, () =>
      assert.fail("empty selection must not be queued"),
    ),
  );
});

test("failed directory preparation queues no files; ordinary drops need no directory API", async () => {
  globalThis.uploadApi = async () => {
    throw new Error("conflict");
  };
  const jobs = [];
  const file = { name: "a.txt", webkitRelativePath: "root/a.txt" };
  await assert.rejects(
    enqueueTree(selectedTree([file]), null, (...args) => jobs.push(args)),
    /conflict/,
  );
  assert.deepEqual(jobs, []);
  const loose = { name: "loose.txt", webkitRelativePath: "" };
  const tree = await droppedTree({
    items: [{ webkitGetAsEntry: () => null }],
    files: [loose],
  });
  await enqueueTree(tree, "current", (...args) => jobs.push(args));
  assert.deepEqual(jobs, [[[loose], "current"]]);
});
