How to Install OpenCode Plugins & Fix "Loaded for Unknown" Error

This guide covers the correct methods for installing plugins in OpenCode, along with a step-by-step troubleshooting process for the "loaded for unknown" error.
Part 1: How to Install Plugins in OpenCode

OpenCode supports two primary ways to install and load plugins: via NPM package configuration or via local JavaScript/TypeScript files.
Method 1: Installing via Config File (opencode.json)

If the plugin is published on NPM (e.g., opencode-plugin-inspector, opencode-plugin-compose):

    Locate your OpenCode configuration file:

        Global Config:

            macOS / Linux: ~/.config/opencode/opencode.json (or opencode.jsonc)

            Windows: %USERPROFILE%\.config\opencode\opencode.json

        Project Config: opencode.json at the root of your project directory.

    Add the plugin package name to the "plugin" array:

    {
      "$schema": "https://opencode.ai/config.json",
      "plugin": [
        "opencode-plugin-inspector",
        "opencode-plugin-notification"
      ]
    }

    Restart OpenCode: OpenCode automatically uses its internal Bun runtime to download, cache, and load the plugins specified in your configuration upon startup.

Method 2: Installing Local Plugins

If you are developing a custom plugin or using a local .js or .ts file:

    Choose the directory:

        Global Plugins (All Projects):

            macOS / Linux: ~/.config/opencode/plugins/

            Windows: %USERPROFILE%\.config\opencode\plugins\

        Project-Specific Plugins:

            Place inside .opencode/plugins/ at your project root.

    Add your plugin file: Create a .js or .ts file (e.g., my-plugin.ts) inside the directory:

    import type { Plugin } from "@opencode-ai/plugin"

    export const MyPlugin: Plugin = async ({ project, client, directory }) => {
      console.log("Plugin initialized for project:", project);

      return {
        // Hook definitions go here
      };
    };

    Restart OpenCode: Local files in these directories are automatically loaded in order when OpenCode launches.

Part 2: Troubleshooting the "Loaded for Unknown" Error

The "loaded for unknown" error occurs when OpenCode identifies a plugin file or package during startup, but cannot map it to a valid export function, recognized hook, or valid project target context.

Follow these steps to diagnose and resolve the issue:
Step 1: Verify Export Syntax in Local Plugins

If you created a local plugin in .opencode/plugins/ or ~/.config/opencode/plugins/, ensure that:

    The function is properly exported as a named or default export returning an object or hook mapping.

    If using TypeScript, make sure there are no syntax errors prevent parsing.

Incorrect:

// Missing export or invalid return shape
function MyPlugin() {
  // ...
}

Correct:

import type { Plugin } from "@opencode-ai/plugin"

export const MyPlugin: Plugin = async (ctx) => {
  return {
    "session.created": async (input) => {
      // Logic here
    }
  };
};

Step 2: Clear the OpenCode Package Cache

If an NPM plugin installation was interrupted or cached improperly, OpenCode may fail to read the plugin metadata.

    Fully close OpenCode.

    Delete the cache directory:

        macOS / Linux:

        rm -rf ~/.cache/opencode

        Windows: Delete the folder located at %USERPROFILE%\.cache\opencode.

    Relaunch OpenCode to force a clean re-installation of configured dependencies.

Step 3: Check opencode.json Formatting

Ensure your opencode.json key is strictly formatted as an array of strings under "plugin" (singular, not "plugins").

{
  "plugin": [
    "example-plugin-name"
  ]
}

Step 4: Isolate the Misbehaving Plugin

If you have multiple plugins enabled:

    Open your opencode.json and set "plugin": [].

    Temporarily rename or move files out of ~/.config/opencode/plugins/ and .opencode/plugins/.

    Restart OpenCode to verify the baseline works.

    Re-enable plugins one by one to identify which specific package or file triggers the error.

Step 5: Verify Git Workspace Initialization

Some plugins require a valid Git repository context to resolve the project name/worktree. If you run OpenCode outside a initialized directory:

    Initialize a Git repository with git init or ensure OpenCode is launched inside an active project folder rather than an orphan/empty directory.