#!/usr/bin/env node
/**
 * Example: a clean TypeScript script that passes all quality gates.
 *
 * Quality gates this script demonstrably satisfies:
 *   - Cyclomatic complexity < 6 for every function (ts/complexity [[2,5]])
 *   - Strict TSConfig types (tsc --strict, noImplicitAny, strictNullChecks)
 *   - No empty catch or swallowed errors (no-empty, no-useless-catch)
 *   - No mutable default arguments (TS avoids this via object.freeze or
 *     undefined defaults)
 *   - All file I/O uses synchronous calls with proper error context
 */

import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { exit } from "node:process";

interface WordFrequency {
  word: string;
  count: number;
}

function readLines(filePath: string): string[] {
  const content: string = readFileSync(filePath, "utf-8");
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function filterComments(lines: string[]): string[] {
  return lines.filter((line) => !line.startsWith("#"));
}

function countWords(lines: string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const line of lines) {
    const words = line.split(/\s+/);
    for (const word of words) {
      if (word.length === 0) continue;
      const current = counts.get(word) ?? 0;
      counts.set(word, current + 1);
    }
  }
  return counts;
}

function topNWords(counts: Map<string, number>, n: number): WordFrequency[] {
  const entries = Array.from(counts.entries());
  entries.sort((a, b) => b[1] - a[1]);
  return entries.slice(0, n).map(([word, count]) => ({ word, count }));
}

function analyzeFile(filePath: string, topN: number = 10): void {
  const lines = readLines(filePath);
  const codeLines = filterComments(lines);
  const counts = countWords(codeLines);
  const top = topNWords(counts, topN);

  console.log(
    `Analyzed ${codeLines.length} non-comment lines in ${basename(filePath)}`,
  );
  console.log("Top words:");
  for (const { word, count } of top) {
    console.log(`  ${word}: ${count}`);
  }
}

function main(): number {
  const args = process.argv.slice(2);
  if (args.length !== 1) {
    console.error(`Usage: ${basename(process.argv[1])} <text-file-path>`);
    return 2;
  }

  const filePath = args[0] as string;
  try {
    analyzeFile(filePath);
  } catch (err: unknown) {
    if (err instanceof Error) {
      console.error(`File error: ${err.message}`);
    } else {
      console.error("Unknown error occurred");
    }
    return 1;
  }
  return 0;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  exit(main());
}

export { analyzeFile, countWords, filterComments, readLines, topNWords };
