import path from 'path';
import fs from 'fs';

/**
 * Enterprise Configuration Module
 * Dynamically resolves environment settings, workspace directories,
 * and sanitizer tokens without any hardcoded local paths.
 */

export interface AppConfig {
  appName: string;
  appEnv: string;
  appPort: number;
  repoRoot: string;
  dataDir: string;
  outputDir: string;
  logDir: string;
  reportsDir: string;
  targetLegacyName: string;
  targetCleanName: string;
  forbiddenPathPatterns: string[];
  enableStrictTyping: boolean;
  enableHygieneScan: boolean;
  strictPathScrubCheck: boolean;
}

/**
 * Load environment variables manually from .env if present
 */
function loadEnvFile(envPath: string): Record<string, string> {
  const envMap: Record<string, string> = {};
  if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, 'utf-8').split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
        const [key, ...valParts] = trimmed.split('=');
        envMap[key.trim()] = valParts.join('=').trim();
      }
    }
  }
  return envMap;
}

const rootDir = process.cwd();
const localEnv = loadEnvFile(path.resolve(rootDir, '.env'));

function getEnv(key: string, defaultValue: string): string {
  return process.env[key] || localEnv[key] || defaultValue;
}

function getEnvBool(key: string, defaultValue: boolean): boolean {
  const val = getEnv(key, String(defaultValue)).toLowerCase();
  return val === 'true' || val === '1';
}

export const config: AppConfig = {
  appName: getEnv('APP_NAME', 'my-repo'),
  appEnv: getEnv('APP_ENV', 'development'),
  appPort: parseInt(getEnv('APP_PORT', '3000'), 10),
  
  // Resolved Portable Relative Paths
  repoRoot: path.resolve(rootDir, getEnv('REPO_ROOT', '.')),
  dataDir: path.resolve(rootDir, getEnv('DATA_DIR', './src/data')),
  outputDir: path.resolve(rootDir, getEnv('OUTPUT_DIR', './dist')),
  logDir: path.resolve(rootDir, getEnv('LOG_DIR', './tests/reports/logs')),
  reportsDir: path.resolve(rootDir, getEnv('REPORTS_DIR', './tests/reports')),

  // Sanitizer Target Tokens
  targetLegacyName: getEnv('TARGET_LEGACY_NAME', 'baziforecaster'),
  targetCleanName: getEnv('TARGET_CLEAN_NAME', 'my-repo'),
  forbiddenPathPatterns: getEnv('FORBIDDEN_PATH_PATTERNS', '/Users/,/home/,C:\\Users\\')
    .split(',')
    .map(p => p.trim()),

  // Feature Flags
  enableStrictTyping: getEnvBool('ENABLE_STRICT_TYPING', true),
  enableHygieneScan: getEnvBool('ENABLE_HYGIENE_SCAN', true),
  strictPathScrubCheck: getEnvBool('STRICT_PATH_SCRUB_CHECK', true)
};

/**
 * Helper to resolve paths relative to repository root
 */
export function resolveRepoPath(...subPaths: string[]): string {
  return path.resolve(config.repoRoot, ...subPaths);
}

export default config;
