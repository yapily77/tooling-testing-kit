import { describe, it, expect } from 'vitest';
import { config } from '../../src/config/index';

describe('03_regression_locks: Critical Invariant Protections', () => {
  it('prevents legacy string leakage in default environment tokens', () => {
    expect(config.targetCleanName).not.toEqual(config.targetLegacyName);
    expect(config.targetCleanName).toEqual('my-repo');
  });

  it('guarantees port number is positive', () => {
    expect(config.appPort).toBeGreaterThan(0);
  });
});
