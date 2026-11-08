import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import ts from "typescript";

const src = new URL("../src/", import.meta.url);
const compile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
    },
  }).outputText;
const moduleUrl = (source) =>
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const catalogUrl = moduleUrl(
  compile(readFileSync(new URL("i18n/en.ts", src), "utf8")),
);
const { en } = await import(catalogUrl);
const runtime = compile(
  readFileSync(new URL("i18n/index.ts", src), "utf8"),
).replace('"./en"', JSON.stringify(catalogUrl));
let moduleId = 0;
async function load(languages, language = "en") {
  const original = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { languages, language },
  });
  try {
    const url = moduleUrl(`${runtime}\n// test instance ${++moduleId}`);
    return { ...(await import(url)), url };
  } finally {
    if (original) Object.defineProperty(globalThis, "navigator", original);
    else delete globalThis.navigator;
  }
}

test("matches supported browser preferences in order, falling back to English", async () => {
  const { detectLocale } = await load([]);
  for (const [languages, expected] of [
    [[], "en"],
    [["fr-FR", "ja-JP"], "en"],
    [["en-GB", "zh-CN"], "en"],
    [["zh-CN", "en-US"], "zh-CN"],
    [["zh-TW"], "zh-CN"],
    [["zh-Hant-HK"], "zh-CN"],
    [["ZH_cn"], "zh-CN"],
    [["fr-FR", "zh"], "zh-CN"],
    [["en-AU"], "en"],
  ])
    assert.equal(detectLocale(languages), expected);
  assert.equal((await load(undefined, "zh-SG")).locale, "zh-CN");
  assert.equal((await load([], "zh-CN")).locale, "zh-CN");
});

test("translates full sentences and preserves interpolated user content", async () => {
  for (const [languages, expected] of [
    [["zh-CN"], "我的文件"],
    [["en-US"], "My files"],
    [["de-DE"], "My files"],
  ]) {
    const { t } = await load(languages);
    assert.equal(t("我的文件"), expected);
    const name = "照片{p0}<script>.png";
    assert.ok(t("选择 {p0}", { p0: name }).endsWith(name));
    assert.ok(t("已选择 {p0} 项", { p0: 1234 }).includes("1,234"));
  }
});

test("every English translation retains exactly the source placeholders", () => {
  const placeholders = (value) =>
    [...value.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
  for (const [source, translated] of Object.entries(en)) {
    assert.ok(translated.trim(), source);
    assert.doesNotMatch(translated, /\p{Script=Han}/u, source);
    assert.deepEqual(placeholders(translated), placeholders(source), source);
  }
});

test("all Chinese UI copy uses the catalog", () => {
  function check(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== "i18n") check(path);
        continue;
      }
      if (!/\.tsx?$/.test(path)) continue;
      const ast = ts.createSourceFile(
        path,
        readFileSync(path, "utf8"),
        ts.ScriptTarget.Latest,
        true,
      );
      function visit(node) {
        if (
          (ts.isStringLiteral(node) || ts.isJsxText(node)) &&
          /\p{Script=Han}/u.test(node.text)
        ) {
          assert.ok(
            ts.isStringLiteral(node) &&
              ts.isCallExpression(node.parent) &&
              node.parent.expression.getText(ast) === "t",
            path,
          );
          assert.ok(Object.hasOwn(en, node.text), `${path}: ${node.text}`);
        }
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
  }
  check(new URL("../src/", import.meta.url).pathname);
});

test("API requests send the selected language and dates use that locale", async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const languages of [["zh-CN"], ["en-GB"], ["ko-KR"]]) {
      const i18n = await load(languages);
      const source = compile(
        readFileSync(new URL("lib/api.ts", src), "utf8"),
      ).replace('"../i18n"', JSON.stringify(i18n.url));
      const api = await import(moduleUrl(source));
      globalThis.fetch = async (url, options) => {
        assert.equal(url, "/api/auth/login");
        assert.equal(options.headers["Accept-Language"], i18n.locale);
        return Response.json(
          { detail: i18n.t("操作失败，请重试") },
          { status: 422 },
        );
      };
      await assert.rejects(api.api("/auth/login", "POST", {}), {
        message: i18n.t("操作失败，请重试"),
      });
      const timestamp = 1800000000;
      assert.equal(
        api.dateTime(timestamp),
        new Intl.DateTimeFormat(i18n.locale, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }).format(timestamp * 1000),
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});
