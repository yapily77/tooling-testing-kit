import { describe, it, expect } from 'vitest';
import { runPreflightCheck } from '../../hygiene/daily/preflight';

describe('08_static_gates: Quality & Hygiene Gates', () => {
  it('passes all daily preflight structural checks', () => {
    const preflight = runPreflightCheck();
    expect(preflight.passed).toBe(true);
  });
});
