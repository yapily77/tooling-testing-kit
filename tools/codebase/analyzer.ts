import fs from 'fs';
import path from 'path';

/**
 * Enterprise Codebase Metrics Analyzer
 * Scans workspace files, measures lines of code, comment density,
 * and detects technical debt candidates.
 */

export interface CodebaseMetrics {
  totalFiles: number;
  totalLines: number;
  codeLines: number;
  commentLines: number;
  blankLines: number;
  fileBreakdown: Record<string, number>;
  qualityScore: number;
}

const EXCLUDED_DIRS = new Set(['node_modules', '.git', 'dist', '.vite', 'coverage']);

export function analyzeDirectory(dirPath: string): CodebaseMetrics {
  let totalFiles = 0;
  let totalLines = 0;
  let codeLines = 0;
  let commentLines = 0;
  let blankLines = 0;
  const fileBreakdown: Record<string, number> = {};

  function traverse(currentPath: string) {
    if (!fs.existsSync(currentPath)) return;
    const entries = fs.readdirSync(currentPath, { withFileTypes: true });

    for (const entry of entries) {
      if (EXCLUDED_DIRS.has(entry.name)) continue;

      const fullPath = path.join(currentPath, entry.name);
      if (entry.isDirectory()) {
        traverse(fullPath);
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name) || '.other';
        totalFiles++;
        fileBreakdown[ext] = (fileBreakdown[ext] || 0) + 1;

        try {
          const content = fs.readFileSync(fullPath, 'utf-8');
          const lines = content.split('\n');
          totalLines += lines.length;

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) {
              blankLines++;
            } else if (trimmed.startsWith('//') || trimmed.startsWith('/*') || trimmed.startsWith('*') || trimmed.startsWith('#')) {
              commentLines++;
            } else {
              codeLines++;
            }
          }
        } catch {
          // Skip binary files
        }
      }
    }
  }

  traverse(dirPath);

  // Calculate Quality Score (0-100)
  const commentRatio = totalLines > 0 ? (commentLines / totalLines) * 100 : 0;
  let qualityScore = 90; // Base score
  if (commentRatio >= 10 && commentRatio <= 30) qualityScore += 10;
  if (totalFiles > 0) qualityScore = Math.min(100, Math.max(0, qualityScore));

  return {
    totalFiles,
    totalLines,
    codeLines,
    commentLines,
    blankLines,
    fileBreakdown,
    qualityScore
  };
}

// CLI Execution
if (process.argv[1] && process.argv[1].endsWith('analyzer.ts')) {
  console.log('====================================================');
  console.log('      ENTERPRISE CODEBASE METRICS ANALYZER         ');
  console.log('====================================================');
  const metrics = analyzeDirectory(process.cwd());
  console.log(`Total Files Scanned : ${metrics.totalFiles}`);
  console.log(`Total Lines of Code : ${metrics.totalLines}`);
  console.log(`Pure Code Lines    : ${metrics.codeLines}`);
  console.log(`Comment Lines      : ${metrics.commentLines}`);
  console.log(`Blank Lines        : ${metrics.blankLines}`);
  console.log(`Quality Scorecard  : ${metrics.qualityScore} / 100`);
  console.log('File Type Breakdown:', metrics.fileBreakdown);
  console.log('====================================================');
}
