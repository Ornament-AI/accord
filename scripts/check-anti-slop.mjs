import { spawnSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const oxlintBin = join(repositoryRoot, "node_modules", "oxlint", "bin", "oxlint");

const fixtureDir = await mkdtemp(join(tmpdir(), "anti-slop-smoke-"));

const validFixture = join(fixtureDir, "valid.ts");

const invalidFixture = join(fixtureDir, "invalid.ts");

try {
  await writeFile(
    validFixture,
    "export const doubled = [1, 2].map((value) => value * 2);\n",
  );
  await writeFile(
    invalidFixture,
    "export const copied = [1, 2].reduce((acc, value) => acc.concat(value), []);\n",
  );

  const run = (fixture) =>
    spawnSync(
      process.execPath,
      [oxlintBin, "--config", ".oxlintrc.json", fixture],
      { cwd: repositoryRoot, encoding: "utf8" },
    );

  const valid = run(validFixture);

  if (valid.status !== 0) {
    process.stderr.write(valid.stderr || valid.stdout);
    throw new Error("anti-slop rejected the valid smoke fixture");
  }

  const invalid = run(invalidFixture);
  const diagnostic = `${invalid.stdout}${invalid.stderr}`;

  if (invalid.status === 0 || !diagnostic.includes("no-reduce-accumulator-copy")) {
    process.stderr.write(diagnostic);
    throw new Error("anti-slop did not reject the accumulator-copy fixture");
  }
} finally {
  await rm(fixtureDir, { recursive: true, force: true });
}
