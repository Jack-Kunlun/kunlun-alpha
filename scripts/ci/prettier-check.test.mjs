import assert from "node:assert/strict";
import test from "node:test";
import { runPrettier } from "./prettier-check.mjs";

test("checks every tracked path without exceeding the Windows command limit", () => {
  const files = Array.from(
    { length: 900 },
    (_, index) => `apps/web/src/features/a long directory/${index}-行情示例.test.tsx`,
  );
  const checked = [];
  const status = runPrettier(files, "--check", (executable, args) => {
    const commandLength = [executable, ...args].join(" ").length + 1;
    if (commandLength >= 32767) return { status: null, error: new Error("E2BIG") };
    assert.equal(args[1], "--check");
    checked.push(...args.slice(2));
    return { status: 0 };
  });
  assert.equal(status, 0);
  assert.deepEqual(checked, files);
});

test("a late batch formatting failure remains a failure", () => {
  const files = Array.from({ length: 900 }, (_, index) => `${"directory/".repeat(7)}${index}.ts`);
  const checked = [];
  const status = runPrettier(files, "--write", (_executable, args) => {
    assert.equal(args[1], "--write");
    checked.push(...args.slice(2));
    return { status: args.includes(files.at(-1)) ? 1 : 0 };
  });
  assert.equal(status, 1);
  assert.deepEqual(checked, files);
});

test("a process launch failure cannot pass the check", () => {
  assert.equal(
    runPrettier(["file.ts"], "--check", () => ({ status: null })),
    1,
  );
});
