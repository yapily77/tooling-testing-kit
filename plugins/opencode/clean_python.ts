// clean_python.ts
//
// Thin OpenCode Plugin: Validated Python File Writer.
// Delegates all quality checks (Ruff, MyPy strict, Radon CC < 6, AST anti-slop)
// to the `clean_py` pip package. This file only handles security gating,
// temp-file hygiene, retry tracking, and sub-process delegation.

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
const retryTracker = new Map<string, { count: number }>();

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

// --- PYTHON INFRASTRUCTURE (delegates all real validation elsewhere) ---
async function getPythonEnvironment(workspaceDir: string): Promise<{ pythonBin: string; venvDir: string }> {
    const venvDir = path.join(workspaceDir, ".venv");
    const candidates = [
        path.join(venvDir, "Scripts", "python.exe"), // Windows
        path.join(venvDir, "bin", "python"),         // Unix
        path.join(venvDir, "bin", "python3"),        // Unix fallback
    ];

    for (const candidate of candidates) {
        const stats = await fs.stat(candidate).catch(() => null);
        if (stats?.isFile()) {
            return { pythonBin: candidate, venvDir };
        }
    }

    throw new InfrastructureError(
        "Python virtual environment not found. Expected a usable Python binary in .venv/bin/python or .venv/Scripts/python.exe."
    );
}

function buildSubprocessEnv(venvDir: string): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = { ...process.env };
    env.VIRTUAL_ENV = venvDir;
    env.PYTHONIOENCODING = "utf-8";
    env.PYTHONDONTWRITEBYTECODE = "1";
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

// --- DELEGATED VALIDATION: clean_py validate <temp_file> ---
async function runCleanPy(pythonBin: string, tempFilePath: string, workspaceDir: string, env: NodeJS.ProcessEnv, displayPath: string): Promise<string[]> {
    const result = await runSubprocess(pythonBin, ["-m", "clean_py", "validate", tempFilePath], workspaceDir, env);

    if (result.exitCode === 0) {
        try {
            const parsed = JSON.parse(result.stdout);
            if (parsed && Array.isArray(parsed.errors) && parsed.errors.length === 0) {
                return [];
            }
            if (parsed && Array.isArray(parsed.errors)) {
                return parsed.errors.map((e: unknown) => String(e));
            }
        } catch {
            return [];
        }
        return [];
    }

    try {
        const parsed = JSON.parse(result.stdout || result.stderr);
        if (parsed && Array.isArray(parsed.errors)) {
            return parsed.errors.map((e: unknown) => String(e));
        }
    } catch {
        const output = result.stdout || result.stderr;
        return [`[CLEAN_PY ERROR]\n${truncate(sanitizeOutput(output, tempFilePath, displayPath))}`];
    }

    return [`[CLEAN_PY ERROR] Non-zero exit (${result.exitCode}) but malformed JSON response.`];
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

    if (path.extname(candidatePath).toLowerCase() !== ".py") {
        throw new SecurityError("Only .py files are allowed to be written by this tool.");
    }

    return candidatePath;
}

// --- TOOL EXPORT ---
export default tool({
    description:
        "Deterministically verifies Python code against strict quality constraints (Ruff, MyPy strict, Radon CC < 6, AST anti-slop) by delegating to the `clean_py` pip package, before atomically writing to disk. Enforces secure writes inside the workspace.",
    args: {
        file_path: tool.schema.string().describe("Relative target path inside the workspace, e.g., 'src/models/user.py'"),
        pydantic_architecture_plan: tool.schema.string().describe("Workflow explanation proving architecture safety & constraint adherence."),
        code_payload: tool.schema.string().describe("Complete Python source code to verify and save."),
    },

    async execute(args, context) {
        try {
            console.log(`[CLEAN PYTHON AUDIT TRAIL] Target: ${args.file_path}`);

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
            if (process.env.DISABLE_CLEAN_PYTHON === "true") {
                await fs.writeFile(absoluteTargetPath, args.code_payload, "utf-8");
                retryTracker.delete(absoluteTargetPath);
                return `[BYPASS ACTIVE] Code written directly to '${displayPath}' without linter checks (DISABLE_CLEAN_PYTHON=true).`;
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

            const { pythonBin, venvDir } = await getPythonEnvironment(workspaceDir);
            const subprocessEnv = buildSubprocessEnv(venvDir);

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
                validationErrors.push(...(await runCleanPy(pythonBin, tempFilePath, workspaceDir, subprocessEnv, displayPath)));

                if (validationErrors.length > 0) {
                    const activeCount = (retryTracker.get(absoluteTargetPath)?.count || 0) + 1;

                    if (activeCount >= MAX_VALIDATION_ATTEMPTS) {
                        retryTracker.delete(absoluteTargetPath);
                        return [
                            `[FATAL QUALITY FAILURE] Could not satisfy quality constraints for '${displayPath}' after ${MAX_VALIDATION_ATTEMPTS} attempts.`,
                            "Action: Fix errors manually, refine prompt/model, or set DISABLE_CLEAN_PYTHON=true to bypass.",
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

                return `SUCCESS: Code passed clean_py quality constraints (Ruff, MyPy strict, Radon CC < 6, AST anti-slop). Saved to '${displayPath}'.`;

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
