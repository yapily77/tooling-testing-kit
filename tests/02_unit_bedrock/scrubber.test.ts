import { describe, it, expect } from 'vitest';
import { PathScrubber } from '../../src/utils/scrubber';

describe('02_unit_bedrock: Path & String Scrubber Unit Tests', () => {
  const scrubber = new PathScrubber('baziforecaster', 'my-repo', ['/Users/', '/home/']);

  it('replaces legacy repository tokens', () => {
    const input = 'Welcome to baziforecaster project';
    const result = scrubber.scrubContent(input);
    expect(result.scrubbedText).toBe('Welcome to my-repo project');
    expect(result.replacementsCount).toBe(1);
  });

  it('scrubs Unix absolute user paths into relative paths', () => {
    const input = 'File path: /Users/alice/projects/app/index.ts';
    const result = scrubber.scrubContent(input);
    expect(result.scrubbedText).toBe('File path: ./projects/app/index.ts');
    expect(result.detectedAbsolutePaths.length).toBeGreaterThan(0);
  });

  it('detects violations in unscrubbed content', () => {
    const input = 'Hardcoded path: /home/bob/secret/baziforecaster';
    const check = scrubber.checkForViolations(input);
    expect(check.hasViolations).toBe(true);
    expect(check.violations.length).toBe(2);
  });
});
