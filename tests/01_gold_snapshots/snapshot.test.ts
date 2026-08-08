import { describe, it, expect } from 'vitest';
import { PathScrubber } from '../../src/utils/scrubber';

describe('01_gold_snapshots: Regression Snapshot Locks', () => {
  const scrubber = new PathScrubber('baziforecaster', 'my-repo', ['/Users/', '/home/']);

  it('matches sanitized configuration snapshot', () => {
    const rawInput = `
    // Configuration File
    const DB_URI = "/Users/dev/projects/baziforecaster/data/app.db";
    const API_ENDPOINT = "https://baziforecaster.internal/api/v1";
    `;

    const result = scrubber.scrubContent(rawInput);

    expect(result.scrubbedText).toContain('my-repo');
    expect(result.scrubbedText).not.toContain('baziforecaster');
    expect(result.scrubbedText).not.toContain('/Users/dev/projects/');
    expect(result.scrubbedText).toMatchSnapshot();
  });
});
