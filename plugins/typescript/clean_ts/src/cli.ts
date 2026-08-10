#!/usr/bin/env node
// cli.ts
//
// CLI entry point for clean_ts.
// Validates TypeScript files using AST policy checks, ESLint-equivalent rule
// checks, and strict type-checking (tsc via subprocess).
//
// Usage:
//   clean_ts validate <file>      — validate a .ts or .tsx file
//   clean_ts --help               — show help
//
// Output: JSON { "valid": boolean, "errors": string[] } on stdout.
// Exit code 0 on success, 1 on validation failure, 2 on infrastructure error.

import { Command } from "commander";
import * as fs from "node:fs/promises";
import type { Stats } from "node:fs";
import * as path from "node:path";
import { validateFile } from "./validator.js";

const program = new Command();

program
  .name("clean_ts")
  .description("Strict TypeScript validator: AST policy, lint rules, and type checking.")
  .version("1.0.0");

program
  .command("validate")
  .description("Validate a TypeScript file against strict quality constraints.")
  .argument("<file>", "Path to the TypeScript file to validate")
  .action(async (filePath: string) => {
    const resolvedPath = path.resolve(filePath);

    let stat: Stats;
    try {
      stat = await fs.stat(resolvedPath);
    } catch {
      console.error(`ERROR: File not found: ${resolvedPath}`);
      process.exit(2);
    }

    if (!stat.isFile()) {
      console.error(`ERROR: Not a regular file: ${resolvedPath}`);
      process.exit(2);
    }

    const ext = path.extname(resolvedPath).toLowerCase();
    if (ext !== ".ts" && ext !== ".tsx") {
      console.error(`ERROR: Only .ts or .tsx files are supported. Got: ${ext}`);
      process.exit(2);
    }

    try {
      const result = await validateFile(resolvedPath);
      console.log(JSON.stringify({ valid: result.valid, errors: result.errors }, null, 2));
      process.exit(result.valid ? 0 : 1);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`ERROR: ${msg}`);
      process.exit(2);
    }
  });

program.parse();
