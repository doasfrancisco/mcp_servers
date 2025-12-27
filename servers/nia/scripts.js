const apiKey = process.env.NIA_API_KEY;

if (!apiKey) {
  console.error("NIA_API_KEY is not set");
  process.exit(1);
}

const response = await fetch("https://apigcp.trynia.ai/v2/usage", {
  headers: {
    Authorization: `Bearer ${apiKey}`,
  },
});

console.log(await response.json());