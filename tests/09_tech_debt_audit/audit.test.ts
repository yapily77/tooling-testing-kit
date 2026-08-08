import { describe, it, expect } from 'vitest';
import { analyzeDirectory } from '../../tools/codebase/analyzer';

describe('09_tech_debt_audit: Codebase Audit & Debt Rating', () => {
  it('achieves Grade A+ Quality Scorecard threshold (>85)', () => {
    const metrics = analyzeDirectory(process.cwd());
    expect(metrics.qualityScore).toBeGreaterThanOrEqual(85);
  });
});
