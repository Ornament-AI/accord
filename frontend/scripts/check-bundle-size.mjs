#!/usr/bin/env node

/**
 * Post-build bundle guardrails.
 *
 * Limits use decimal KB (1000 bytes), matching common CI and hosting reports.
 */
import { readdir, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const distDir = path.join(root, "dist");
const assetsDir = path.join(distDir, "assets");

const KB = 1000;
const budgets = [
	// Optional until a route eagerly pulls recharts into the chart-vendor split.
	{ label: "chart-vendor", pattern: /^chart-vendor-.*\.js$/, maxKb: 575, optional: true },
	{ label: "ui-vendor", pattern: /^ui-vendor-.*\.js$/, maxKb: 335 },
	{ label: "react-vendor", pattern: /^react-vendor-.*\.js$/, maxKb: 325 },
	{ label: "index", pattern: /^index-.*\.js$/, maxKb: 200 },
];

async function listFiles(dir) {
	const entries = await readdir(dir, { withFileTypes: true });
	const files = [];
	for (const entry of entries) {
		const fullPath = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			files.push(...(await listFiles(fullPath)));
		} else if (entry.isFile()) {
			files.push(fullPath);
		}
	}
	return files;
}

function relative(file) {
	return path.relative(root, file);
}

async function readAssetsDir() {
	try {
		return await readdir(assetsDir);
	} catch (error) {
		if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
			console.error("dist/assets not found — run vite build first");
			process.exit(1);
		}
		throw error;
	}
}

const failures = [];
const assetNames = await readAssetsDir();

for (const budget of budgets) {
	const matches = assetNames.filter((name) => budget.pattern.test(name));
	if (matches.length === 0 && budget.optional) {
		continue;
	}
	if (matches.length !== 1) {
		failures.push(
			`${budget.label}: expected exactly one ${budget.pattern}, found ${matches.length}`,
		);
		continue;
	}

	const file = path.join(assetsDir, matches[0]);
	const sizeBytes = (await stat(file)).size;
	const maxBytes = budget.maxKb * KB;
	if (sizeBytes > maxBytes) {
		failures.push(
			`${relative(file)} is ${(sizeBytes / KB).toFixed(1)} KB, max ${budget.maxKb} KB`,
		);
	}
}

const builtFiles = await listFiles(distDir);
const woffFiles = builtFiles.filter((file) => file.endsWith(".woff"));
if (woffFiles.length > 0) {
	failures.push(`dist contains .woff files: ${woffFiles.map(relative).join(", ")}`);
}

if (failures.length > 0) {
	console.error("Bundle size check failed:");
	for (const failure of failures) {
		console.error(`- ${failure}`);
	}
	process.exit(1);
}

console.log("Bundle size check passed.");
