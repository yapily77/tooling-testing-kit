declare module "@opencode-ai/plugin" {
    type PluginInput = {
        client: unknown;
        project: unknown;
        directory: string;
        worktree: string;
        experimental_workspace: unknown;
        serverUrl: URL;
        $: unknown;
    };
    type PluginOptions = Record<string, unknown>;
    type ToolResult = string | {
        title?: string;
        output: string;
        metadata?: Record<string, unknown>;
    };
    type ToolContext = {
        directory: string;
        worktree: string;
    };
    type ToolDefinition = {
        description: string;
        args: Record<string, unknown>;
        execute(args: Record<string, unknown>, context: ToolContext): Promise<ToolResult>;
    };
    type Hooks = {
        tool?: {
            [key: string]: ToolDefinition;
        };
    };
    type Plugin = (input: PluginInput, options?: PluginOptions) => Promise<Hooks>;

    type SchemaString = {
        describe(description: string): SchemaString;
    };
    type Schema = {
        string(): SchemaString;
    };

    interface CleanPythonArgs {
        file_path: string;
        pydantic_architecture_plan: string;
        code_payload: string;
    }

    const tool: {
        schema: Schema;
        <T extends CleanPythonArgs>(input: {
            description: string;
            args: Record<string, SchemaString>;
            execute(args: T, context: ToolContext): Promise<ToolResult>;
        }): ToolDefinition;
    };

    export {
        type Plugin,
        type PluginInput,
        type PluginOptions,
        type ToolResult,
        type ToolContext,
        type ToolDefinition,
        type Hooks,
        CleanPythonArgs,
        tool,
    };
}
