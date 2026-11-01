#!/usr/bin/env node
// Launch only the repo-local MCP server, using its project virtual environment.
import { spawn } from "node:child_process";
import { statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const launcherPath = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(launcherPath), "../../..");

export function runtimePaths(root, platform = process.platform) {
  return {
    python: path.join(root, ".venv", platform === "win32" ? "Scripts" : "bin",
      platform === "win32" ? "python.exe" : "python"),
    server: path.join(root, "tools", "mcp", "repo_health", "server.py"),
  };
}

function isFile(filename) {
  try {
    return statSync(filename).isFile();
  } catch {
    return false;
  }
}

export function launch() {
  const { python, server } = runtimePaths(repoRoot);
  const setup = process.platform === "win32" ? "py -3" : "python3";
  if (process.argv.length !== 2) {
    console.error("repo-health launcher accepts no arguments; it runs only server.py.");
    process.exitCode = 1;
    return;
  }
  if (!isFile(python) || !isFile(server)) {
    console.error("repo-health requires this checkout's .venv and tools/mcp/repo_health/server.py.");
    console.error(`From ${repoRoot}, run: ${setup} -m venv .venv`);
    console.error(`Then run: "${python}" -m pip install -r tools/mcp/repo_health/requirements.txt`);
    process.exitCode = 1;
    return;
  }
  const child = spawn(python, [server], { cwd: repoRoot, stdio: "inherit" });
  const signals = ["SIGINT", "SIGTERM"];
  const handlers = signals.map(signal => {
    const handler = () => child.kill(signal);
    process.on(signal, handler);
    return handler;
  });
  child.on("error", error => {
    console.error(`repo-health could not start its .venv Python (${error.code || "error"}).`);
    console.error(`Repair this checkout's .venv; no global interpreter fallback is used.`);
    process.exitCode = 1;
  });
  child.on("close", code => {
    signals.forEach((signal, index) => process.removeListener(signal, handlers[index]));
    process.exitCode = code === null ? 1 : code;
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === launcherPath) {
  launch();
}
