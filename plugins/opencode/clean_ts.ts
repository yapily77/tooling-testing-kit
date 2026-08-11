// clean_ts.ts
//
// Thin OpenCode Plugin: Validated TypeScript File Writer.
// Delegates all quality checks (AST policy, tsc strict, ESLint-equivalent rules,
// cyclomatic complexity < 6, type safety) to the `clean_ts` Node CLI.
// This file only handles security gating, temp-file hygiene, retry tracking,
// and sub-process delegation.

import type { Plugin } from "@opencode-ai/plugin";
import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

// --- CONFIGURATION ---
const MAX_VALIDATION_ATTEMPTS = 10;
const OUTPUT_LIMIT = 20_000;
const MAX_TRACKER_SIZE = 1000;

// --- STATE MANAGEMENT ---
interface RetryState {
    count: number;
}
const retryTracker = new Map<string, RetryState>();

class SecurityError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "SecurityError";
    }
}

class InfrastructureError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "InfrastructureError";
    }
}

// --- UTILITIES ---
function truncate(value: string, limit: number = OUTPUT_LIMIT): string {
    if (!value) return "";
    if (value.length <= limit) return value;
    return `${value.slice(0, limit)}\n... output truncated`;
}

function sanitizeOutput(rawOutput: string, tempPath: string, targetPath: string): string {
    if (!rawOutput) return "";
    try {
        const escapedTempPath = tempPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        return rawOutput.replace(new RegExp(escapedTempPath, "g"), targetPath).trim();
    } catch {
        return rawOutput.trim();
    }
}

// --- NODE INFRASTRUCTURE (delegates all real validation elsewhere) ---
// Mirrors getPythonEnvironment(): discover the `clean_ts` CLI entry point.
// Resolution order:
//   1. workspaceRoot/node_modules/clean_ts/dist/cli.js   (installed Node package)
//   2. workspaceRoot/plugins/typescript/clean_ts/dist/cli.js (local monorepo build)
//   3. workspaceRoot/node_modules/.bin/clean_ts          (npx-installed shim, executed directly)
async function getNodeEnvironment(workspaceDir: string): Promise<{ nodeBin: string; cliPath: string; directExec: boolean }> {
    const nodeBin = "node";
    const candidateJsFiles = [
        path.join(workspaceDir, "node_modules", "clean_ts", "dist", "cli.js"),
        path.join(workspaceDir, "plugins", "typescript", "clean_ts", "dist", "cli.js"),
        path.join(workspaceDir, "plugins", "typescript", "dist", "cli.js"),
    ];
    for (const candidate of candidateJsFiles) {
        const candidateStat = await fs.stat(candidate).catch(() => null);
        if (candidateStat?.isFile()) {
            return { nodeBin, cliPath: candidate, directExec: false };
        }
    }

    // Fall back to the npx-installed bin shim (executed directly, not via `node`).
    const localBin = path.join(workspaceDir, "node_modules", ".bin", "clean_ts");
    const localStat = await fs.stat(localBin).catch(() => null);
    if (localStat?.isFile()) {
        return { nodeBin: localBin, cliPath: localBin, directExec: true };
    }

    throw new InfrastructureError(
        "clean_ts CLI not found. Expected a 'clean_ts' Node package with dist/cli.js, a prebuilt plugins/typescript/clean_ts/dist/cli.js, or 'node_modules/.bin/clean_ts'."
    );
}

function buildSubprocessEnv(): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = { ...process.env };
    env.NODE_NO_WARNINGS = "1";
    return env;
}

async function runSubprocess(cmd: string, args: string[], cwd: string, env: NodeJS.ProcessEnv): Promise<{ stdout: string; stderr: string; exitCode: number }> {
    try {
        const { stdout, stderr } = await execFileAsync(cmd, args, {
            cwd,
            timeout: 30_000,
            maxBuffer: 10 * 1024 * 1024,
            env,
        });
        return { stdout, stderr, exitCode: 0 };
    } catch (error: any) {
        return {
            stdout: error.stdout ?? "",
            stderr: error.stderr ?? error.message ?? "",
            exitCode: typeof error.code === "number" ? error.code : 1,
        };
    }
}

// --- DELEGATED VALIDATION: clean_ts validate <temp_file> ---
async function runCleanTs(nodeBin: string, cliPath: string, directExec: boolean, tempFilePath: string, workspaceDir: string, env: NodeJS.ProcessEnv, displayPath: string): Promise<string[]> {
    const result = directExec
        ? await runSubprocess(nodeBin, ["validate", tempFilePath], workspaceDir, env)
        : await runSubprocess(nodeBin, [cliPath, "validate", tempFilePath], workspaceDir, env);

    const output = result.stdout || result.stderr;
    try {
        const parsed = JSON.parse(output);
        if (parsed?.errors && Array.isArray(parsed.errors) && parsed.errors.length === 0 && parsed.valid === true) {
            return [];
        }
        if (parsed?.errors && Array.isArray(parsed.errors)) {
            return parsed.errors.map((e: unknown) => String(e));
        }
    } catch {
        // Intentional: output may not be JSON (e.g. human-readable errors or non-JSON stdout/stderr)
        void 0;
    }

    if (result.exitCode === 0) {
        return [];
    }

    return [`[CLEAN_TS ERROR] Non-zero exit (${result.exitCode}). Output:\n${truncate(sanitizeOutput(output, tempFilePath, displayPath))}`];
}

// --- SECURITY & PATH SANITIZATION ---
async function resolveSecureTargetPath(workspaceDir: string, filePath: string): Promise<string> {
    if (typeof filePath !== "string" || filePath.trim().length === 0) {
        throw new SecurityError("file_path must be a non-empty string.");
    }

    if (/[\0\n\r]/.test(filePath)) {
        throw new SecurityError("file_path contains forbidden control characters.");
    }

    if (path.isAbsolute(filePath)) {
        throw new SecurityError("file_path must be a relative workspace path.");
    }

    const candidatePath = path.resolve(workspaceDir, filePath);
    const rel = path.relative(workspaceDir, candidatePath);

    if (!rel || rel === "." || path.isAbsolute(rel) || rel.split(path.sep)[0] === "..") {
        throw new SecurityError("file_path resolves outside the allowed workspace (Path traversal detected).");
    }

    const normalizedRel = rel.split(path.sep).join("/").toLowerCase();
    const deniedDirectories = [".git", ".opencode", ".venv", "node_modules"];

    for (const denied of deniedDirectories) {
        if (normalizedRel === denied || normalizedRel.startsWith(`${denied}/`)) {
            throw new SecurityError(`Writing into '${denied}' is strictly forbidden.`);
        }
    }

    const ext = path.extname(candidatePath).toLowerCase();
    if (ext !== ".ts" && ext !== ".tsx") {
        throw new SecurityError("Only .ts and .tsx files are allowed to be written by this tool.");
    }

    return candidatePath;
}

// --- TOOL EXPORT ---
export const cleanTsTool = tool({
    description:
        "Deterministically verifies TypeScript code against strict quality constraints (AST policy, tsc strict, ESLint-equivalent rules, cyclomatic complexity < 6, type safety) by delegating to the `clean_ts` Node CLI, before atomically writing to disk. Enforces secure writes inside the workspace.",
    args: {
        file_path: tool.schema.string().describe("Relative target path inside the workspace, e.g., 'src/models/user.ts'"),
        pydantic_architecture_plan: tool.schema.string().describe("Workflow explanation proving architecture safety & constraint adherence."),
        code_payload: tool.schema.string().describe("Complete TypeScript source code to verify and save."),
    },

    async execute(args, context) {
        try {
            console.log(`[CLEAN TYPESCRIPT AUDIT TRAIL] Target: ${args.file_path}`);

            const rawWorkspaceDir = path.resolve(context?.directory || process.cwd());
            let workspaceDir: string;
            try {
                workspaceDir = await fs.realpath(rawWorkspaceDir);
            } catch {
                return "INFRASTRUCTURE ERROR: Workspace directory could not be resolved.";
            }

            const absoluteTargetPath = await resolveSecureTargetPath(workspaceDir, args.file_path);
            const displayPath = path.relative(workspaceDir, absoluteTargetPath).split(path.sep).join("/");

            const targetDir = path.dirname(absoluteTargetPath);
            await fs.mkdir(targetDir, { recursive: true });

            // Check for Bypass Flag
            if (process.env.DISABLE_CLEAN_TS === "true") {
                await fs.writeFile(absoluteTargetPath, args.code_payload, "utf-8");
                retryTracker.delete(absoluteTargetPath);
                return `[BYPASS ACTIVE] Code written directly to '${displayPath}' without linter checks (DISABLE_CLEAN_TS=true).`;
            }

            // Manage Tracker Size
            if (retryTracker.size > MAX_TRACKER_SIZE) {
                const oldestKey = retryTracker.keys().next().value;
                if (oldestKey) retryTracker.delete(oldestKey);
            }

            let targetExists = false;
            try {
                const stat = await fs.lstat(absoluteTargetPath);
                if (stat.isSymbolicLink() || stat.isDirectory()) {
                    return "SECURITY VIOLATION: Target file must not be a symlink or directory.";
                }
                targetExists = true;
            } catch (err: any) {
                if (err.code !== "ENOENT") return `INFRASTRUCTURE ERROR: Unable to stat target file: ${err.message}`;
            }

            const { nodeBin, cliPath, directExec } = await getNodeEnvironment(workspaceDir);
            const subprocessEnv = buildSubprocessEnv();

            // Create secure temporary file
            const tempFileName = `.tmp-${crypto.randomUUID()}-${path.basename(absoluteTargetPath)}`;
            const tempFilePath = path.join(targetDir, tempFileName);
            let tempFileCreated = false;

            try {
                const handle = await fs.open(tempFilePath, "wx", 0o600);
                tempFileCreated = true;
                await handle.writeFile(args.code_payload, "utf-8");
                await handle.close();

                const validationErrors: string[] = [];
                validationErrors.push(...(await runCleanTs(nodeBin, cliPath, directExec, tempFilePath, workspaceDir, subprocessEnv, displayPath)));

                if (validationErrors.length > 0) {
                    const activeCount = (retryTracker.get(absoluteTargetPath)?.count || 0) + 1;

                    if (activeCount >= MAX_VALIDATION_ATTEMPTS) {
                        retryTracker.delete(absoluteTargetPath);
                        return [
                            `[FATAL QUALITY FAILURE] Could not satisfy quality constraints for '${displayPath}' after ${MAX_VALIDATION_ATTEMPTS} attempts.`,
                            "Action: Fix errors manually, refine prompt/model, or set DISABLE_CLEAN_TS=true to bypass.",
                            "---",
                            validationErrors.join("\n\n"),
                        ].join("\n");
                    }

                    retryTracker.set(absoluteTargetPath, { count: activeCount });

                    return [
                        "VALIDATION FAILED. Do not apologize. Do not output conversational text.",
                        `Fix the specific errors below and invoke the tool again. (Attempt ${activeCount}/${MAX_VALIDATION_ATTEMPTS})`,
                        "---",
                        validationErrors.join("\n\n"),
                    ].join("\n");
                }

                // Atomic File System Rename
                await fs.rename(tempFilePath, absoluteTargetPath);
                retryTracker.delete(absoluteTargetPath);

                return `SUCCESS: Code passed clean_ts quality constraints (AST policy, tsc strict, ESLint-equivalent rules, cyclomatic complexity < 6, type safety). Saved to '${displayPath}'.`;

            } finally {
                if (tempFileCreated) {
                    await fs.unlink(tempFilePath).catch(() => { });
                }
            }
        } catch (error: any) {
            if (error instanceof SecurityError) return `SECURITY VIOLATION: ${error.message}`;
            if (error instanceof InfrastructureError) return `INFRASTRUCTURE ERROR: ${error.message}`;
            return `FATAL ERROR: ${error?.message ?? String(error)}`;
        }
    },
});

export const cleanTsPlugin: Plugin = async () => {
    return {
        tool: {
            clean_ts: cleanTsTool,
        },
    };
};

(cleanTsPlugin as any).id = "clean-ts";

export default {
    id: "clean-ts",
    server: cleanTsPlugin,
};
