import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const themeRequire = createRequire(require.resolve("@heroui/theme"));
const entry = themeRequire.resolve("deepmerge");

for (const [name, merge] of [
  ["cjs", themeRequire("deepmerge")],
  ["umd", themeRequire(join(dirname(entry), "umd.js"))],
]) {
  test(`${name}: rejects prototype poisoning from either input`, () => {
    const hostile = JSON.parse(
      '{"__proto__":{"elevated":true},"constructor":{"prototype":{"elevated":true}},"prototype":{"elevated":true}}',
    );
    for (const merged of [
      merge(Object.create(null), hostile),
      merge(hostile, {}),
    ]) {
      assert.equal(Object.getPrototypeOf(merged), Object.prototype);
      assert.equal(merged.elevated, undefined);
      for (const key of ["__proto__", "constructor", "prototype"]) {
        assert.equal(Object.hasOwn(merged, key), false);
      }
    }
    assert.equal({}.elevated, undefined);
  });

  test(`${name}: preserves normal nested theme merging`, () => {
    const symbol = Symbol("theme");
    assert.deepEqual(
      merge(
        { colors: { primary: "blue" }, values: [1], [symbol]: 3 },
        { colors: { accent: "green" }, values: [2] },
      ),
      {
        colors: { primary: "blue", accent: "green" },
        values: [1, 2],
        [symbol]: 3,
      },
    );
  });
}
