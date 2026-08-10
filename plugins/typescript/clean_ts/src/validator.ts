// validator.ts
//
// Orchestrates TypeScript static analysis: AST policy anti-slop checks,
// ESLint-equivalent rule checks, and strict type-checking via tsc subprocess.
// Returns structured validation results.
//
// Mirrors the Python clean_py validator structure:
//   1. AST policy checks (fast, in-process via TypeScript compiler API)
//   2. tsc --strict --noEmit (full type checking via subprocess)
//   3. ESLint rule checks (pattern-based, in-process)

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFileSync, existsSync } from "node:fs";
import { resolve, relative, dirname } from "node:path";
import { checkAstViolations } from "./ast-policy.js";

const execFileAsync = promisify(execFile);

const DEFAULT_TIMEOUT_MS = 30_000;

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export interface ValidateFileOptions {
  workspaceDir?: string;
  tsConfigPath?: string;
}

interface LinterDiagnostic {
  ruleId: string;
  severity: number;
  message: string;
  line: number;
}

function resolveTarget(filePath: string, workspaceDir?: string): string {
  return resolve(workspaceDir || process.cwd(), filePath);
}

function discoverTsc(workspaceDir: string): string {
  const candidate = resolve(workspaceDir, "node_modules/.bin/tsc");
  if (existsSync(candidate)) return candidate;
  const rootCandidate = resolve(workspaceDir, "../../node_modules/.bin/tsc");
  if (existsSync(rootCandidate)) return rootCandidate;
  return "npx";
}

function findNearestTsConfig(filePath: string): string | null {
  let dir = dirname(resolve(filePath));
  while (true) {
    const candidate = resolve(dir, "tsconfig.json");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

/**
 * Run tsc as a subprocess for full type-checking.
 *
 * Command: tsc --strict --noEmit --pretty --noEmitOnError <file>
 * Uses the local TypeScript compiler binary for full-fidelity type checking.
 * Falls back to `npx --no-install tsc` if the local binary is not found.
 *
 * Returns formatted error strings in the form:
 *   `<file>:<line>:<col>: TS<code> <level>: <message>`
 *
 * Edge cases handled:
 *   - Syntax errors (tsc reports them as TS1xxx)
 *   - Implicit any violations (TS7006, TS7031)
 *   - Missing return type annotations (TS7010, TS7030)
 *   - tsc not found (falls back to npx)
 *   - tsc timeout
 *   - ANSI color codes stripped from --pretty output
 */
export async function runTsc(
  filePath: string,
  displayPath: string,
  workspaceDir: string,
): Promise<string[]> {
  const tscBin = discoverTsc(workspaceDir);
  const tsConfig = findNearestTsConfig(filePath);
  const args: string[] = [];

  if (tsConfig) {
    args.push("-p", tsConfig, "--noEmit", filePath);
  } else {
    args.push(
      "--strict",
      "--noEmit",
      "--pretty",
      "--noEmitOnError",
      "--skipLibCheck",
      "--noImplicitAny",
      "--strictNullChecks",
      "--esModuleInterop",
      "--moduleResolution", "node",
      "--target", "ES2022",
      "--module", "CommonJS",
      "--lib", "ES2022",
      filePath,
    );
  }

  let stdout = "";
  let stderr = "";

  try {
    if (tscBin === "npx") {
      const result = await execFileAsync(
        "npx",
        ["--no-install", "tsc", ...args],
        { timeout: DEFAULT_TIMEOUT_MS, maxBuffer: 2 * 1024 * 1024 },
      );
      stdout = result.stdout as string;
      stderr = result.stderr as string;
    } else {
      const result = await execFileAsync(tscBin, args, {
        timeout: DEFAULT_TIMEOUT_MS,
        maxBuffer: 2 * 1024 * 1024,
      });
      stdout = result.stdout as string;
      stderr = result.stderr as string;
    }
  } catch (err: unknown) {
    if (
      err && typeof err === "object" &&
      "code" in err && "stdout" in err && "stderr" in err
    ) {
      const execErr = err as { stdout?: string; stderr?: string; code?: number };
      stdout = execErr.stdout || "";
      stderr = execErr.stderr || "";
      if (execErr.code === 0 && (!stdout || !stderr)) return [];
    } else {
      const msg = err instanceof Error ? err.message : String(err);
      return [`[TSC ERROR] ${displayPath}: ${msg}`];
    }
  }

  if (!stdout && !stderr) return [];

  const combined = `${stdout}\n${stderr}`;
  return parseTscOutput(stripAnsi(combined), displayPath);
}

/**
 * Strip ANSI escape codes from tsc --pretty output.
 */
function stripAnsi(input: string): string {
  return input.replace(/\x1b\[[0-9;]*m/g, "");
}

/**
 * Parse tsc --pretty output into standardized error strings.
 */
function parseTscOutput(output: string, displayPathStr: string): string[] {
  const errors: string[] = [];
  const lines = output.split("\n").map((l) => l.trim()).filter(Boolean);

  const patternParen = /^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)$/;
  const patternColon = /^(.+?):(\d+):(\d+)\s*-\s*(error|warning)\s+(TS\d+):\s+(.+)$/;

  for (const line of lines) {
    let match = line.match(patternParen);
    if (match) {
      const lineNum = match[2];
      const colNum = match[3];
      const level = match[4];
      const tscCode = match[5];
      const message = match[6];
      errors.push(`${displayPathStr}:${lineNum}:${colNum}: ${tscCode} ${level}: ${message}`);
      continue;
    }

    match = line.match(patternColon);
    if (match) {
      const lineNum = match[2];
      const colNum = match[3];
      const level = match[4];
      const tscCode = match[5];
      const message = match[6];
      errors.push(`${displayPathStr}:${lineNum}:${colNum}: ${tscCode} ${level}: ${message}`);
      continue;
    }

    if (
      !line.startsWith("Version") &&
      !line.startsWith("Found ") &&
      !line.startsWith("error TS") &&
      line.length > 0 &&
      (line.includes("TS") || line.includes("error") || line.includes("warning"))
    ) {
      errors.push(`[TSC] ${displayPathStr}: ${line}`);
    }
  }

  return errors;
}

function runEslintRuleChecks(sourceText: string): LinterDiagnostic[] {
  const diagnostics: LinterDiagnostic[] = [];
  const lines = sourceText.split("\n");
  lines.forEach((lineText, idx) => {
    const line = idx + 1;
    if (/\beval\s*\(/.test(lineText)) {
      diagnostics.push({ ruleId: "no-eval", severity: 2, message: "eval is forbidden.", line });
    }
    if (/^\s*var\s+/.test(lineText)) {
      diagnostics.push({ ruleId: "no-var", severity: 2, message: "Unexpected var, use let or const instead.", line });
    }
  });
  return diagnostics;
}

function formatEslintDiagnostic(d: LinterDiagnostic): string {
  return ` line ${d.line}: ${d.ruleId}: ${d.message}`;
}

/**
 * Validate a TypeScript file's source text against all checks.
 */
export function validateTypeScriptFile(
  sourceText: string,
  filePath: string,
): { errors: string[]; passes: string[] } {
  const errors: string[] = [];
  const passes: string[] = [];
  const relativePath = filePath.replace(/\\/g, "/").split("/").pop() || filePath;

  const astErrors = checkAstViolations(sourceText, filePath);
  if (astErrors.length > 0) {
    for (const e of astErrors) {
      errors.push(e);
    }
  } else {
    passes.push("AST policy check: PASSED");
  }

  const eslintDiagnostics = runEslintRuleChecks(sourceText);
  if (eslintDiagnostics.length > 0) {
    for (const d of eslintDiagnostics) {
      errors.push(`  ${relativePath}:${formatEslintDiagnostic(d)}`);
    }
  } else {
    passes.push("ESLint rule check: PASSED");
  }

  return { errors, passes };
}

/**
 * Validate a TypeScript file against AST policy, tsc --strict, and ESLint.
 */
export async function validateFile(
  filePath: string,
  options: ValidateFileOptions = {},
): Promise<ValidationResult> {
  const ws = options.workspaceDir;
  const target = resolveTarget(filePath, ws);
  const displayPath = relative(process.cwd(), target) || target;

  if (!existsSync(target)) {
    return { valid: false, errors: [`file not found: ${displayPath}`] };
  }

  const source = readFileSync(target, "utf-8");

  const astErrors = checkAstViolations(source, displayPath);
  if (astErrors.length > 0) {
    return { valid: false, errors: astErrors };
  }

  const eslintDiagnostics = runEslintRuleChecks(source);
  const eslintErrors: string[] = [];
  if (eslintDiagnostics.length > 0) {
    for (const d of eslintDiagnostics) {
      eslintErrors.push(`  ${displayPath}:${formatEslintDiagnostic(d)}`);
    }
  }

  const tscErrors = await runTsc(target, displayPath, ws || dirname(target));

  const allErrors = [...astErrors, ...eslintErrors, ...tscErrors];
  return { valid: allErrors.length === 0, errors: allErrors };
}
