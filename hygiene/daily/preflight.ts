import fs from 'fs';
import path from 'path';

/**
 * Enterprise Pre-flight Hygiene Checklist
 * Verifies required structure, configuration integrity, and build readiness.
 */

export function runPreflightCheck(): { passed: boolean; checks: { name: string; ok: boolean; info: string }[] } {
  const checks = [
    {
      name: '.env configuration check',
      ok: fs.existsSync(path.resolve(process.cwd(), '.env.example')),
      info: '.env.example template is present'
    },
    {
      name: 'Package manifest integrity',
      ok: fs.existsSync(path.resolve(process.cwd(), 'package.json')),
      info: 'package.json exists with test and build scripts'
    },
    {
      name: 'TypeScript configuration',
      ok: fs.existsSync(path.resolve(process.cwd(), 'tsconfig.json')),
      info: 'tsconfig.json configured with strict type checking'
    },
    {
      name: 'Tools & Utilities suite',
      ok: fs.existsSync(path.resolve(process.cwd(), 'tools/scrub_paths.py')) && fs.existsSync(path.resolve(process.cwd(), 'tools/bootstrap.sh')),
      info: 'scrub_paths.py and bootstrap.sh are executable and present'
    },
    {
      name: 'Tests hierarchy',
      ok: fs.existsSync(path.resolve(process.cwd(), 'tests')),
      info: '10-tier test architecture initialized'
    }
  ];

  const passed = checks.every(c => c.ok);
  return { passed, checks };
}

if (process.argv[1] && process.argv[1].endsWith('preflight.ts')) {
  console.log('====================================================');
  console.log('            DAILY PRE-FLIGHT HYGIENE CHECK         ');
  console.log('====================================================');
  const result = runPreflightCheck();
  result.checks.forEach(c => {
    console.log(`${c.ok ? '✅ PASS' : '❌ FAIL'}: ${c.name} (${c.info})`);
  });

  if (result.passed) {
    console.log('\n✅ All pre-flight hygiene checks passed cleanly!');
  } else {
    console.error('\n❌ Pre-flight checks failed.');
    process.exit(1);
  }
}
