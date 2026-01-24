import { metorial } from '@metorial/mcp-server-sdk';
import { ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { TwitterApi } from 'twitter-api-v2';

interface Config {
  TWITTER_API_CONSUMER_KEY: string;
  TWITTER_API_CONSUMER_SECRET: string;
  TWITTER_ACCESS_TOKEN_KEY: string;
  TWITTER_ACCESS_TOKEN_SECRET: string;
}

metorial.createServer<Config>(
  { name: 'catafract', version: '1.0.0' },
  async (server: any, args: Config) => {

    // Create Twitter client using args (from launch params)
    const getTwitterClient = () => {
      return new TwitterApi({
        appKey: args.TWITTER_API_CONSUMER_KEY,
        appSecret: args.TWITTER_API_CONSUMER_SECRET,
        accessToken: args.TWITTER_ACCESS_TOKEN_KEY,
        accessSecret: args.TWITTER_ACCESS_TOKEN_SECRET,
      });
    };

    const postToTwitter = async (message: string) => {
      const client = getTwitterClient();
      const result = await client.v2.tweet(message);
      return `https://x.com/i/web/status/${result.data.id}`;
    };

    server.registerTool('list-services', {
      title: 'List Services',
      description: 'List available social media services',
      inputSchema: { dummy: z.string().optional() }
    }, async () => ({
      content: [{ type: 'text' as const, text: 'Available services:\n✅ X (formerly Twitter) (ID: twitter, limit: 280 chars)' }]
    }));

    server.registerTool('post-to-twitter', {
      title: 'Post to Twitter',
      description: 'Post a message to Twitter/X',
      inputSchema: { message: z.string() }
    }, async ({ message }: { message: string }) => {
      try {
        const url = await postToTwitter(message);
        return { content: [{ type: 'text' as const, text: `✅ Posted: ${url}` }] };
      } catch (error: unknown) {
        const errMsg = error instanceof Error ? error.message : String(error);
        return { content: [{ type: 'text' as const, text: `❌ Failed: ${errMsg}` }] };
      }
    });

    server.registerTool('check-message-length', {
      title: 'Check Message Length',
      description: 'Check if message fits Twitter 280 char limit',
      inputSchema: { message: z.string() }
    }, async ({ message }: { message: string }) => {
      const fits = message.length <= 280;
      const text = fits
        ? `✅ Fits: ${message.length}/280 chars`
        : `❌ Too long: ${message.length}/280 (excess: ${message.length - 280})`;
      return { content: [{ type: 'text' as const, text }] };
    });
  }
);