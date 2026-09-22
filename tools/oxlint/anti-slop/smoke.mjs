import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const oxlint = join(root, "node_modules", "oxlint", "bin", "oxlint");
const config = existsSync(join(root, "oxlint.config.ts"))
  ? join(root, "oxlint.config.ts")
  : join(root, ".oxlintrc.json");
const fixtureDirectory = mkdtempSync(join(root, ".anti-slop-regression-"));
const fixture = join(fixtureDirectory, "fixture.ts");

const cases = [
  {
    name: "custom reduce methods are not treated as array reducers",
    rule: "anti-slop/no-reduce-accumulator-copy",
    violation: false,
    source: "type Processor = { reduce<T>(callback: (accumulator: T, value: number) => T, initial: T): T };\n\ndeclare const processor: Processor;\n\nprocessor.reduce<number[]>((accumulator, value) => accumulator.concat(value), []);",
  },
  {
    name: "inline array accumulator copies are rejected",
    rule: "anti-slop/no-reduce-accumulator-copy",
    violation: true,
    source: "[1, 2].reduce((accumulator, value) => accumulator.concat(value), []);",
  },
  {
    name: "concat arguments that copy the accumulator are rejected",
    rule: "anti-slop/no-reduce-accumulator-copy",
    violation: true,
    source: "[1, 2].reduce((accumulator, value) => [].concat(accumulator, value), []);",
  },
  {
    name: "referenced reducer callbacks and constructed arrays are checked",
    rule: "anti-slop/no-reduce-accumulator-copy",
    violation: true,
    source: "const reducer = (accumulator: number[], value: number) => accumulator.concat(value);\n\n[1, 2].reduce(reducer, new Array<number>());",
  },
  {
    name: "function declaration reducers are checked",
    rule: "anti-slop/no-reduce-accumulator-copy",
    violation: true,
    source: "function reducer(accumulator: number[], value: number) { return accumulator.concat(value); }\n\n[1, 2].reduce(reducer, []);",
  },
  {
    name: "broad Record aliases and absorbing key unions are detected",
    rule: "anti-slop/no-widen-then-assert",
    violation: true,
    source: "type Bag = Record<string | \"fixed\", unknown>;\n\ntype Model = { id: number };\n\nconst value: Bag = { id: 1 };\n\nvalue as Model;",
  },
  {
    name: "aliased object widening is detected",
    rule: "anti-slop/no-widen-then-assert",
    violation: true,
    source: "type Broad = object;\n\ntype Model = { id: number };\n\nconst value: Broad = { id: 1 };\n\nvalue as Model;",
  },
  {
    name: "satisfies evidence survives widening",
    rule: "anti-slop/no-widen-then-assert",
    violation: true,
    source: "type Model = { id: number };\n\nconst value: unknown = ({ id: 1 } satisfies Model);\n\nvalue as Model;",
  },
  {
    name: "a local Record type does not use built-in Record semantics",
    rule: "anti-slop/no-widen-then-assert",
    violation: false,
    source: "declare class Record<K, V> {}\n\ntype Bag = Record<string, unknown>;\n\ntype Model = { id: number };\n\nconst value: Bag = {};\n\nvalue as Model;",
  },
  {
    name: "a local Promise type is not treated as the global Promise",
    rule: "anti-slop/no-unknown-returns",
    violation: false,
    source: "interface Promise<T> { value: T }\n\ndeclare function customPromise(): Promise<unknown>;",
  },
  {
    name: "the global Promise unknown return remains rejected",
    rule: "anti-slop/no-unknown-returns",
    violation: true,
    source: "declare function globalPromise(): Promise<unknown>;",
  },
  {
    name: "class expression names do not shadow outer type aliases",
    rule: "anti-slop/no-unknown-type-aliases",
    violation: true,
    source: "type Identity<T> = T;\n\nconst value = class Identity {};\n\ntype Hidden = Identity<unknown>;",
  },
];

function lintCase(testCase) {
  writeFileSync(fixture, `${testCase.source}\n\n`);
  let failed = false;
  let output = "";
  try {
    output = execFileSync(
      process.execPath,
      [oxlint, "--config", config, "--no-ignore", "--allow", "all", "--deny", testCase.rule, fixture],
      { cwd: root, encoding: "utf8", stdio: "pipe" },
    );
  } catch (error) {
    failed = true;
    output = String(error.stdout ?? "") + String(error.stderr ?? "");
  }

  const reported = output.includes(`anti-slop(${testCase.rule.slice("anti-slop/".length)})`);
  if (testCase.violation !== reported || (failed && !reported)) {
    throw new Error(`Anti-slop regression smoke failed: ${testCase.name}\n\n${output}`);
  }
}

try {
  for (const testCase of cases) lintCase(testCase);
} finally {
  rmSync(fixtureDirectory, { recursive: true, force: true });
}
