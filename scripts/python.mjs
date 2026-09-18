/**
 * Run a Python script through the repo's own interpreter.
 *
 * `npm run dev` starts both halves, and the Python half used to be a bare
 * `python orchestrator/server.py`. That resolves to whatever is on PATH, so a
 * shell without the venv activated got `ModuleNotFoundError: No module named
 * 'uvicorn'` and no indication that a virtualenv was the point.
 *
 * Prefers .venv, falls back to PATH, and says which one it picked when the
 * import fails.
 *
 *   node scripts/python.mjs orchestrator/server.py --offline
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

const candidates = [
  join(ROOT, ".venv", "Scripts", "python.exe"), // Windows
  join(ROOT, ".venv", "bin", "python"), // macOS, Linux
];

const venv = candidates.find((p) => existsSync(p));
const interpreter = venv ?? (process.platform === "win32" ? "python" : "python3");

if (!venv) {
  console.error(
    `[python] no .venv found, using '${interpreter}' from PATH.\n` +
      `[python] if imports fail:  python -m venv .venv && pip install -r requirements.txt`,
  );
}

const child = spawn(interpreter, process.argv.slice(2), {
  cwd: ROOT,
  stdio: "inherit",
});

child.on("error", (err) => {
  console.error(`[python] could not start '${interpreter}': ${err.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  // Forward the signal rather than swallowing it, so Ctrl-C through
  // concurrently still reads as an interrupt instead of a crash.
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 0);
});
