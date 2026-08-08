import { describe, it, expect } from 'vitest';
import { config, resolveRepoPath } from '../../src/config/index';

describe('02_unit_bedrock: Config & Path Resolvers', () => {
  it('loads environment defaults cleanly without hardcoded paths', () => {
    expect(config.appName).toBeDefined();
    expect(config.targetCleanName).toBe('my-repo');
    expect(config.targetLegacyName).toBe('baziforecaster');
  });

  it('resolves relative repository paths correctly', () => {
    const resolvedPath = resolveRepoPath('src', 'config');
    expect(resolvedPath).toContain('src');
    expect(resolvedPath).not.toContain('/Users/hardcoded');
  });
});
