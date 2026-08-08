import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

/**
 * Enterprise Test Harness Orchestrator
 * Runs test suites, aggregates results, and logs reports to tests/reports/
 */

export function runTestSuite(suiteName = 'all'): { success: boolean; output: string } {
  console.log(`\n====================================================`);
  console.log(`   EXECUTING TEST SUITE: ${suiteName.toUpperCase()}`);
  console.log(`====================================================`);

  const reportsDir = path.resolve(process.cwd(), 'tests/reports/logs');
  if (!fs.existsSync(reportsDir)) {
    fs.mkdirSync(reportsDir, { recursive: true });
  }

  try {
    let command = 'npx vitest run';
    if (suiteName === 'unit') command = 'npx vitest run tests/02_unit_bedrock';
    if (suiteName === 'e2e') command = 'npx vitest run tests/05_integration_e2e';

    const output = execSync(command, { encoding: 'utf-8', stdio: 'pipe' });
    const logFile = path.join(reportsDir, `test_run_${Date.now()}.log`);
    fs.writeFileSync(logFile, output, 'utf-8');

    console.log(output);
    console.log(`\n[SUCCESS] Test suite executed cleanly. Logged to ${logFile}`);
    return { success: true, output };
  } catch (error: any) {
    const errorOutput = error.stdout || error.stderr || error.message;
    console.error(`[FAILURE] Test suite encountered errors:\n`, errorOutput);
    return { success: false, output: errorOutput };
  }
}

if (process.argv[1] && process.argv[1].endsWith('runner.ts')) {
  const suite = process.argv[2] || 'all';
  runTestSuite(suite);
}
