import { metorial } from '@metorial/mcp-server-sdk';
import { z } from 'zod';

interface Config {
  SUPERMEMORY_CLIENT_ID: string;
  SUPERMEMORY_REFRESH_TOKEN: string;
  SUPERMEMORY_ACCESS_TOKEN?: string; // Optional - use directly if provided
}

const TOKEN_ENDPOINT = "https://api.supermemory.ai/api/auth/mcp/token";
const SERVER_URL = "https://api.supermemory.ai/mcp";
const FETCH_TIMEOUT_MS = 15000; // 15 second timeout per request

let currentAccessToken: string | null = null;
let sessionId: string | null = null;
let isSessionInitialized: boolean = false;
let requestId: number = 1;
let debugLogs: string[] = [];

const log = (msg: string) => {
  debugLogs.push(`[${new Date().toISOString()}] ${msg}`);
  console.log(`[supermemory] ${msg}`);
};

const clearLogs = () => {
  debugLogs = [];
};

const getLogsAndClear = () => {
  const logs = debugLogs.join('\n');
  debugLogs = [];
  return logs;
};

// Fetch with timeout
const fetchWithTimeout = async (url: string, options: RequestInit, timeoutMs: number = FETCH_TIMEOUT_MS): Promise<Response> => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    log(`Fetch timeout after ${timeoutMs}ms, aborting...`);
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error: any) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs}ms`);
    }
    throw error;
  }
};

// Refresh access token
const refreshAccessToken = async (args: Config): Promise<string> => {
  log("Refreshing access token...");
  const response = await fetchWithTimeout(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: args.SUPERMEMORY_REFRESH_TOKEN,
      client_id: args.SUPERMEMORY_CLIENT_ID,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    log(`Token refresh failed: ${response.status} - ${errorText}`);
    throw new Error(`Token refresh failed: ${response.status}`);
  }

  const data = await response.json() as { access_token: string };
  currentAccessToken = data.access_token;
  log("Token refreshed successfully");
  return data.access_token;
};

// Initialize MCP session with Supermemory
const initializeSession = async (args: Config): Promise<void> => {
  if (isSessionInitialized) {
    log("Session already initialized, skipping");
    return;
  }

  log("Starting MCP session initialization...");
  const response = await sendMcpRequestRaw(args, "initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "supermemory-proxy", version: "1.0.0" }
  });

  log(`Initialize response: ${JSON.stringify(response)}`);

  if (response?.result) {
    isSessionInitialized = true;
    log("Sending notifications/initialized...");
    await sendMcpRequestRaw(args, "notifications/initialized", undefined);
    log("Session initialization complete");
  } else {
    log("No result in initialize response, marking initialized anyway");
    isSessionInitialized = true;
  }
};

// Raw MCP request (no session check)
const sendMcpRequestRaw = async (args: Config, method: string, params?: any): Promise<any> => {
  if (!currentAccessToken) {
    // Try using provided access token first, otherwise refresh
    if (args.SUPERMEMORY_ACCESS_TOKEN) {
      log("Using provided access token directly");
      currentAccessToken = args.SUPERMEMORY_ACCESS_TOKEN;
    } else {
      currentAccessToken = await refreshAccessToken(args);
    }
  }

  const isNotification = method.startsWith("notifications/");
  const message: any = {
    jsonrpc: "2.0",
    method,
  };

  // Only include id for requests, NOT for notifications
  if (!isNotification) {
    message.id = requestId++;
  }

  if (params !== undefined) {
    message.params = params;
  }

  log(`Sending ${method}: ${JSON.stringify(message)}`);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Authorization": `Bearer ${currentAccessToken}`,
  };

  if (sessionId) {
    headers["Mcp-Session-Id"] = sessionId;
    log(`Using session ID: ${sessionId.substring(0, 20)}...`);
  }

  const response = await fetchWithTimeout(SERVER_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(message),
  });

  log(`Response status: ${response.status}`);

  if (response.status === 401) {
    log("Got 401, refreshing token...");
    currentAccessToken = await refreshAccessToken(args);
    return sendMcpRequestRaw(args, method, params);
  }

  if (!response.ok) {
    const errorBody = await response.text();
    log(`Error response: ${errorBody}`);
    throw new Error(`MCP request failed: ${response.status} - ${errorBody}`);
  }

  const newSessionId = response.headers.get("Mcp-Session-Id");
  if (newSessionId && newSessionId !== sessionId) {
    sessionId = newSessionId;
    log(`Got new session ID: ${sessionId.substring(0, 20)}...`);
  }

  const text = await response.text();
  log(`Response body length: ${text.length}`);

  const lines = text.split("\n");

  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const data = line.slice(6);
      if (data.trim()) {
        log(`Parsed SSE data`);
        return JSON.parse(data);
      }
    }
  }

  // Try parsing as direct JSON if not SSE format
  if (text.trim()) {
    try {
      const parsed = JSON.parse(text);
      log(`Parsed direct JSON`);
      return parsed;
    } catch {
      log(`Response not JSON: ${text.substring(0, 100)}`);
    }
  }

  log("No parseable response");
  return null;
};

// Send MCP request to supermemory (with session initialization)
const sendMcpRequest = async (args: Config, method: string, params?: any): Promise<any> => {
  // Initialize session first if needed
  if (!isSessionInitialized) {
    await initializeSession(args);
  }
  return sendMcpRequestRaw(args, method, params);
};

// Call a supermemory tool
const callSupermemoryTool = async (config: Config, toolName: string, toolArgs: any): Promise<any> => {
  clearLogs();
  log(`Calling tool: ${toolName} with args: ${JSON.stringify(toolArgs)}`);

  try {
    const response = await sendMcpRequest(config, "tools/call", {
      name: toolName,
      arguments: toolArgs,
    });

    log(`Tool response: ${JSON.stringify(response)}`);

    if (response?.result?.content) {
      const logs = getLogsAndClear();
      // Return result with debug logs appended
      const content = response.result.content;
      if (Array.isArray(content) && content.length > 0 && content[0].type === 'text') {
        content.push({ type: 'text', text: `\n\n--- DEBUG LOGS ---\n${logs}` });
      }
      return content;
    }
    if (response?.error) {
      throw new Error(response.error.message);
    }
    const logs = getLogsAndClear();
    return [{ type: 'text', text: `Response: ${JSON.stringify(response)}\n\n--- DEBUG LOGS ---\n${logs}` }];
  } catch (error: any) {
    const logs = getLogsAndClear();
    throw new Error(`${error.message}\n\n--- DEBUG LOGS ---\n${logs}`);
  }
};

// ===== MCP SERVER =====
metorial.createServer<Config>(
  { name: 'supermemory', version: '1.0.0' },
  async (server: any, args: Config) => {

    server.registerTool('addMemory', {
      title: 'Add Memory',
      description: 'Store information in supermemory',
      inputSchema: {
        thingToRemember: z.string().describe('The content to remember'),
        projectId: z.string().optional().describe('Optional project ID')
      }
    }, async ({ thingToRemember, projectId }: { thingToRemember: string; projectId?: string }) => {
      const result = await callSupermemoryTool(args, 'addMemory', { thingToRemember, projectId });
      return { content: result };
    });

    server.registerTool('search', {
      title: 'Search Memories',
      description: 'Search through stored memories',
      inputSchema: {
        informationToGet: z.string().describe('What to search for'),
        projectId: z.string().optional().describe('Optional project ID to filter')
      }
    }, async ({ informationToGet, projectId }: { informationToGet: string; projectId?: string }) => {
      const result = await callSupermemoryTool(args, 'search', { informationToGet, projectId });
      return { content: result };
    });

    server.registerTool('getProjects', {
      title: 'Get Projects',
      description: 'List all projects',
      inputSchema: { dummy: z.string().optional() }
    }, async () => {
      const result = await callSupermemoryTool(args, 'getProjects', {});
      return { content: result };
    });

    server.registerTool('whoAmI', {
      title: 'Who Am I',
      description: 'Get current user info',
      inputSchema: { dummy: z.string().optional() }
    }, async () => {
      const result = await callSupermemoryTool(args, 'whoAmI', {});
      return { content: result };
    });
  }
);
