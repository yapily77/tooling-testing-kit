import fs from 'fs';
import path from 'path';

/**
 * Enterprise Documentation & Context Helper
 * Allows searching repository docs, guides, and plans locally.
 */

export interface SearchResult {
  filePath: string;
  line: number;
  snippet: string;
}

export function searchDocumentation(query: string, searchDir = process.cwd()): SearchResult[] {
  const results: SearchResult[] = [];
  const lowercaseQuery = query.toLowerCase();

  function scan(dir: string) {
    if (!fs.existsSync(dir)) return;
    const entries = fs.readdirSync(dir, { withFileTypes: true });

    for (const entry of entries) {
      if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === 'dist') continue;
      const fullPath = path.join(dir, entry.name);

      if (entry.isDirectory()) {
        scan(fullPath);
      } else if (entry.isFile() && (entry.name.endsWith('.md') || entry.name.endsWith('.txt') || entry.name.endsWith('.json'))) {
        try {
          const lines = fs.readFileSync(fullPath, 'utf-8').split('\n');
          lines.forEach((line, idx) => {
            if (line.toLowerCase().includes(lowercaseQuery)) {
              results.push({
                filePath: path.relative(process.cwd(), fullPath),
                line: idx + 1,
                snippet: line.trim()
              });
            }
          });
        } catch {
          // Skip unreadable files
        }
      }
    }
  }

  scan(searchDir);
  return results;
}

if (process.argv[1] && process.argv[1].endsWith('doc_search.ts')) {
  const query = process.argv[2] || 'Accenture';
  console.log(`[DOC SEARCH] Searching repository for: "${query}"...`);
  const matches = searchDocumentation(query);
  console.log(`Found ${matches.length} matching snippets:`);
  matches.slice(0, 10).forEach(m => {
    console.log(`  - ${m.filePath}:${m.line} -> "${m.snippet}"`);
  });
}
