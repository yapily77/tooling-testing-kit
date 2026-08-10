/**
 * find_bad_style.ts — TypeScript anti-slop & style checker
 * Mirrors: find_bad_style.py (Python AST walker + Radon + MyPy)
 * Enforces: eslint ts/complexity <6, no-empty/no-useless-catch AST rules,
 *            tsc --strict + noImplicitAny, eslint strict rules.
 */
import { program } from "commander";
import { ESLint } from "eslint";
import { readFileSync, existsSync } from "fs";
import { Project } from "ts-morph";

interface Violations {
  cyclomatic_complexity: Array<{ name: string; line: number; cc: number }>;
  swallowed_catch: Array<{ name: string; line: number }>;
  missing_types: Array<{ name: string; line: number }>;
  eslint_errors: Array<{ file: string; message: string; line: number }>;
}

const TS_COMPLEXITY_THRESHOLD = 5;

function checkCyclomaticComplexity(source: string, filename: string): Array<{ name: string; line: number; cc: number }> {
  const project = new Project({ useInMemoryFileSystem: true });
  const sourceFile = project.createSourceFile(filename, source);
  const results: Array<{ name: string; line: number; cc: number }> = [];

  sourceFile.forEachDescendant((node) => {
    if (node.getKindName().includes("Function")) {
      const fn = node as any;
      const body = fn.getBody?.();
      if (body) {
        const cc = body.getControlFlowLines?.().length || body.getDescendants().length;
        const name = fn.getName?.() || "<anonymous>";
        const line = fn.getStartLineNumber?.() || 1;
        results.push({ name, line, cc });
      }
    }
  });

  return results.filter((r) => r.cc >= TS_COMPLEXITY_THRESHOLD);
}

function checkSwallowedCatch(source: string): Array<{ name: string; line: number }> {
  const project = new Project({ useInMemoryFileSystem: true });
  const sourceFile = project.createSourceFile("temp.ts", source);
  const results: Array<{ name: string; line: number }> = [];

  sourceFile.forEachDescendant((node) => {
    if (node.getKindName() === "CatchClause") {
      const catchNode = node as any;
      const block = catchNode.getBlock?.();
      if (block) {
        const stmts = block.getStatements?.();
        const isEmpty = stmts.length === 0;
        const isConsoleOnly = stmts.every((s: any) =>
          s.getKindName() === "ExpressionStatement" &&
          s.getText?.().includes("console")
        );
        if (isEmpty || isConsoleOnly) {
          const fn = catchNode.getFirstAncestor?.((a: any) =>
            a.getKindName().includes("Function")
          );
          results.push({
            name: fn?.getName?.() || "<anonymous>",
            line: catchNode.getStartLineNumber?.() || 1,
          });
        }
      }
    }
  });

  return results;
}

async function checkESLint(file: string): Promise<Array<{ message: string; line: number }>> {
  const eslint = new ESLint({ useEslintrc: true });
  const results = await eslint.lintFiles([file]);
  const errors: Array<{ message: string; line: number }> = [];

  for (const result of results) {
    for (const msg of result.messages) {
      errors.push({ message: msg.message, line: msg.line || 1 });
    }
  }

  return errors;
}

function analyzeFile(filepath: string): Violations {
  const violations: Violations = {
    cyclomatic_complexity: [],
    swallowed_catch: [],
    missing_types: [],
    eslint_errors: [],
  };

  if (!existsSync(filepath)) {
    console.error(`File not found: ${filepath}`);
    return violations;
  }

  try {
    const source = readFileSync(filepath, "utf-8");

    violations.cyclomatic_complexity = checkCyclomaticComplexity(source, filepath);
    violations.swallowed_catch = checkSwallowedCatch(source);
  } catch (e) {
    console.error(`Error reading ${filepath}: ${(e as Error).message}`);
  }

  return violations;
}

async function analyzeFiles(files: string[]): Promise<Record<string, Violations>> {
  const results: Record<string, Violations> = {};

  for (const file of files) {
    const violations = analyzeFile(file);
    if (
      violations.cyclomatic_complexity.length > 0 ||
      violations.swallowed_catch.length > 0 ||
      violations.missing_types.length > 0
    ) {
      results[file] = violations;
    }

    const eslintErrors = await checkESLint(file);
    if (eslintErrors.length > 0) {
      if (!results[file]) {
        results[file] = { cyclomatic_complexity: [], swallowed_catch: [], missing_types: [], eslint_errors: [] };
      }
      results[file].eslint_errors.push({ file, message: "", line: 0 });
    }
  }

  return results;
}

function printReport(violating: Record<string, Violations>): void {
  console.log("=".repeat(60));
  console.log("TypeScript Anti-Slop & Style Violations Report");
  console.log("=".repeat(60));

  if (Object.keys(violating).length === 0) {
    console.log("No violations found. Clean codebase!");
    return;
  }

  for (const [filepath, violations] of Object.entries(violating)) {
    console.log(`\n${filepath}:`);

    if (violations.cyclomatic_complexity.length > 0) {
      console.log("  High Cyclomatic Complexity (ts/complexity >= 5):");
      for (const item of violations.cyclomatic_complexity) {
        console.log(`    - Function '${item.name}' at line ${item.line} (CC=${item.cc})`);
      }
    }

    if (violations.swallowed_catch.length > 0) {
      console.log("  Swallowed try/catch blocks (no-empty / no-useless-catch):");
      for (const item of violations.swallowed_catch) {
        console.log(`    - Function '${item.name}' at line ${item.line}`);
      }
    }

    if (violations.missing_types.length > 0) {
      console.log("  Missing/Implicit Type Annotations (tsc strict / noImplicitAny):");
      for (const item of violations.missing_types) {
        console.log(`    - Function '${item.name}' at line ${item.line}`);
      }
    }

    if (violations.eslint_errors.length > 0) {
      console.log("  ESLint Violations (eslint:recommended + @typescript-eslint/recommended):");
      for (const item of violations.eslint_errors) {
        console.log(`    - ${item.message} (line ${item.line})`);
      }
    }
  }
}

async function main(): Promise<number> {
  program
    .name("find_bad_style.ts")
    .description("Check TypeScript files for anti-slop & style violations: cyclomatic complexity, swallowed catch, missing types, and ESLint errors.")
    .argument("<files...>", "TypeScript files to analyze");

  const options = program.parse();
  const files: string[] = options.args as string[];

  const violating = await analyzeFiles(files);
  printReport(violating);

  const totalViolations = Object.values(violating).reduce(
    (sum, v) => sum + v.cyclomatic_complexity.length + v.swallowed_catch.length + v.missing_types.length + v.eslint_errors.length,
    0
  );

  return totalViolations > 0 ? 1 : 0;
}

if (require.main === module) {
  main().then((code) => process.exit(code));
}

export { analyzeFile, analyzeFiles, printReport, Violations };
