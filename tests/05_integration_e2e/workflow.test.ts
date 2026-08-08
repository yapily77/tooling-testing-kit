import { describe, it, expect } from 'vitest';
import { analyzeDirectory } from '../../tools/codebase/analyzer';
import { scanRepositoryForPathViolations } from '../../hygiene/scanners/path_scrub_check';

describe('05_integration_e2e: End-to-End Quality Workflows', () => {
  it('runs complete codebase analysis workflow', () => {
    const metrics = analyzeDirectory(process.cwd());
    expect(metrics.totalFiles).toBeGreaterThan(0);
    expect(metrics.qualityScore).toBeGreaterThanOrEqual(80);
  });

  it('runs hygiene scanner workflow cleanly', () => {
    const scanResult = scanRepositoryForPathViolations(process.cwd());
    expect(scanResult.totalScanned).toBeGreaterThan(0);
  });
});
