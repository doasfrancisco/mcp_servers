import { metorial } from '@metorial/mcp-server-sdk';
import { ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { TwitterApi } from 'twitter-api-v2';

interface Config {}

// ===== TWITTER CLIENT =====
let twitterClient: TwitterApi | null = null;

const getTwitterClient = () => {
  if (!twitterClient) {
    const appKey = process.env.TWITTER_API_CONSUMER_KEY;
    const appSecret = process.env.TWITTER_API_CONSUMER_SECRET;
    const accessToken = process.env.TWITTER_ACCESS_TOKEN_KEY;
    const accessSecret = process.env.TWITTER_ACCESS_TOKEN_SECRET;

    if (!appKey || !appSecret || !accessToken || !accessSecret) {
      throw new Error('Twitter credentials not configured. Required: TWITTER_API_CONSUMER_KEY, TWITTER_API_CONSUMER_SECRET, TWITTER_ACCESS_TOKEN_KEY, TWITTER_ACCESS_TOKEN_SECRET');
    }

    twitterClient = new TwitterApi({
      appKey,
      appSecret,
      accessToken,
      accessSecret,
    });
  }
  return twitterClient;
};

const postToTwitter = async (message: string) => {
  const client = getTwitterClient();
  const result = await client.v2.tweet(message);
  return {
    platform: 'twitter',
    id: result.data.id,
    url: `https://x.com/i/web/status/${result.data.id}`,
  };
};

// ===== SERVICE MAP =====
const services: Record<string, {
  name: string;
  post: (msg: string) => Promise<{ platform: string; id: string; url: string }>;
  limit: number;
  configured: () => boolean;
}> = {
  twitter: {
    name: 'X (formerly Twitter)',
    post: postToTwitter,
    limit: 280,
    configured: () => !!(
      process.env.TWITTER_API_CONSUMER_KEY &&
      process.env.TWITTER_API_CONSUMER_SECRET &&
      process.env.TWITTER_ACCESS_TOKEN_KEY &&
      process.env.TWITTER_ACCESS_TOKEN_SECRET
    ),
  },
};

// ===== MCP SERVER =====
metorial.createServer<Config>(
  {
    name: 'catafract',
    version: '1.0.0'
  },
  async (server: any, args: any) => {

    server.registerTool(
      'list-services',
      {
        title: 'List Services',
        description: 'List all available social media services and their configuration status',
        inputSchema: { dummy: z.string().optional() }
      },
      async () => {
        const serviceList = Object.entries(services)
          .map(([id, s]) => {
            const status = s.configured() ? '✅' : '❌';
            return `${status} ${s.name} (ID: ${id}, limit: ${s.limit} chars)`;
          })
          .join('\n');

        return {
          content: [{ type: 'text' as const, text: `Available services:\n${serviceList}` }]
        };
      }
    );

    server.registerTool(
      'post-to-social-media',
      {
        title: 'Post to Social Media',
        description: 'Post a message to one or more platforms. Use comma-separated IDs: twitter',
        inputSchema: {
          message: z.string().describe('The message to post'),
          platforms: z.string().describe('Comma-separated platform IDs: twitter')
        }
      },
      async ({ message, platforms }: { message: string; platforms: string }) => {
        const platformList = platforms.split(',').map((p: string) => p.trim().toLowerCase());
        const results: string[] = [];

        for (const platformId of platformList) {
          const service = services[platformId];

          if (!service) {
            results.push(`❌ ${platformId}: Unknown platform`);
            continue;
          }

          if (!service.configured()) {
            results.push(`❌ ${service.name}: Not configured (missing credentials)`);
            continue;
          }

          try {
            const result = await service.post(message);
            results.push(`✅ ${service.name}: ${result.url}`);
          } catch (error: unknown) {
            const errMsg = error instanceof Error ? error.message : String(error);
            results.push(`❌ ${service.name}: ${errMsg}`);
          }
        }

        return {
          content: [{ type: 'text' as const, text: results.join('\n') }]
        };
      }
    );

    server.registerTool(
      'check-message-length',
      {
        title: 'Check Message Length',
        description: 'Check if message fits within platform character limits',
        inputSchema: {
          message: z.string().describe('The message to check'),
          platforms: z.string().optional().describe('Comma-separated platform IDs (default: all)')
        }
      },
      async ({ message, platforms }: { message: string; platforms?: string }) => {
        const platformList = platforms
          ? platforms.split(',').map((p: string) => p.trim().toLowerCase())
          : Object.keys(services);

        const results = platformList.map((platformId: string) => {
          const service = services[platformId];
          if (!service) return `❓ ${platformId}: Unknown platform`;

          const fits = message.length <= service.limit;
          return fits
            ? `✅ ${service.name}: ${message.length}/${service.limit} chars`
            : `❌ ${service.name}: ${message.length}/${service.limit} chars (excess: ${message.length - service.limit})`;
        });

        return {
          content: [{ type: 'text' as const, text: results.join('\n') }]
        };
      }
    );
  }
);
