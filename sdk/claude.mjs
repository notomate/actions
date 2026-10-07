// Runs one Claude Agent SDK query with no tools and prints the result as JSON.
// Input (stdin): {"prompt": str, "model": str, "schema": object | null}
// Output (stdout): {"subtype", "is_error", "result", "structured_output"}
import { query } from "@anthropic-ai/claude-agent-sdk";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function reply(message) {
  process.stdout.write(JSON.stringify(message));
}

const request = await readStdin();
// Credentials arrive as ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN from the
// Python caller, which already removed the action's other INPUT_* variables.
const options = {
  tools: [],
  allowedTools: [],
  mcpServers: {},
  strictMcpConfig: true,
  settingSources: [],
  persistSession: false,
  model: request.model,
  env: { ...process.env },
};
if (request.schema) {
  options.outputFormat = { type: "json_schema", schema: request.schema };
}

try {
  for await (const message of query({ prompt: request.prompt, options })) {
    if (message.type === "result") {
      reply({
        subtype: message.subtype,
        is_error: message.is_error,
        result: message.result ?? "",
        structured_output: message.structured_output ?? null,
      });
      process.exit(0);
    }
  }
  reply({ subtype: "no_result", is_error: true });
} catch (error) {
  // Error messages can echo request details; the caller reports only the subtype.
  reply({ subtype: `exception: ${error?.name ?? "Error"}`, is_error: true });
}
process.exit(1);
