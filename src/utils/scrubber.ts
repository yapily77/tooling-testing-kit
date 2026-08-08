import { config } from '../config/index';

/**
 * Enterprise Path & String Sanitizer Utility
 * Sanitizes hardcoded user machine paths and legacy project identifiers.
 */

export interface ScrubResult {
  originalText: string;
  scrubbedText: string;
  replacementsCount: number;
  detectedLegacyTokens: string[];
  detectedAbsolutePaths: string[];
}

export class PathScrubber {
  private legacyToken: string;
  private cleanToken: string;
  private forbiddenPatterns: string[];

  constructor(
    legacyToken = config.targetLegacyName,
    cleanToken = config.targetCleanName,
    forbiddenPatterns = config.forbiddenPathPatterns
  ) {
    this.legacyToken = legacyToken;
    this.cleanToken = cleanToken;
    this.forbiddenPatterns = forbiddenPatterns;
  }

  /**
   * Sanitizes text content by replacing legacy project tokens and scrubbing absolute paths
   */
  public scrubContent(content: string): ScrubResult {
    let scrubbed = content;
    let replacementsCount = 0;
    const detectedLegacyTokens: string[] = [];
    const detectedAbsolutePaths: string[] = [];

    // 1. Scrub Legacy Name (e.g., baziforecaster -> my-repo)
    if (this.legacyToken && scrubbed.includes(this.legacyToken)) {
      const regex = new RegExp(this.legacyToken, 'g');
      const matches = scrubbed.match(regex);
      if (matches) {
        replacementsCount += matches.length;
        detectedLegacyTokens.push(this.legacyToken);
      }
      scrubbed = scrubbed.replace(regex, this.cleanToken);
    }

    // 2. Scrub Absolute User Paths (e.g., /Users/johndoe/projects/... -> ./projects/...)
    // UNIX absolute path regex: /Users/username/ or /home/username/
    const unixUserPathRegex = /\/(Users|home)\/[a-zA-Z0-9_\-\.]+\//g;
    const unixMatches = scrubbed.match(unixUserPathRegex);
    if (unixMatches) {
      unixMatches.forEach(match => detectedAbsolutePaths.push(match));
      replacementsCount += unixMatches.length;
      scrubbed = scrubbed.replace(unixUserPathRegex, './');
    }

    // Windows absolute path regex: C:\Users\username\
    const winUserPathRegex = /[A-Z]:\\Users\\[a-zA-Z0-9_\-\.]+\\/gi;
    const winMatches = scrubbed.match(winUserPathRegex);
    if (winMatches) {
      winMatches.forEach(match => detectedAbsolutePaths.push(match));
      replacementsCount += winMatches.length;
      scrubbed = scrubbed.replace(winUserPathRegex, '.\\');
    }

    return {
      originalText: content,
      scrubbedText: scrubbed,
      replacementsCount,
      detectedLegacyTokens,
      detectedAbsolutePaths
    };
  }

  /**
   * Checks if content contains any unscrubbed forbidden patterns or legacy tokens
   */
  public checkForViolations(content: string): { hasViolations: boolean; violations: string[] } {
    const violations: string[] = [];

    if (this.legacyToken && content.includes(this.legacyToken)) {
      violations.push(`Found legacy identifier: '${this.legacyToken}'`);
    }

    for (const pattern of this.forbiddenPatterns) {
      if (pattern && content.includes(pattern)) {
        violations.push(`Found forbidden absolute path pattern: '${pattern}'`);
      }
    }

    return {
      hasViolations: violations.length > 0,
      violations
    };
  }
}

export default new PathScrubber();
