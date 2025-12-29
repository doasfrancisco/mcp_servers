 To Regenerate X API Credentials:

  1. Go to the X Developer Portal: https://developer.x.com/en/portal/dashboard
  2. Select your App from the project list
  3. For API Key & Secret (OAuth 1.0a):
    - Go to "Keys and tokens" tab
    - Under "Consumer Keys", click "Regenerate"
    - Save the new API Key and API Key Secret
  4. For Access Token & Secret (OAuth 1.0a):
    - Same page, under "Authentication Tokens"
    - Click "Regenerate" for Access Token and Secret
    - Save both values
  5. For OAuth 2.0 Client ID & Secret (what your code uses):
    - Under "OAuth 2.0 Client ID and Client Secret"
    - Regenerate if needed

 Here's the mapping:

  | Crosspost expects           | Your key              |
  |-----------------------------|-----------------------|
  | TWITTER_API_CONSUMER_KEY    | X_API_KEY             |
  | TWITTER_API_CONSUMER_SECRET | X_API_KEY_SECRET      |
  | TWITTER_ACCESS_TOKEN_KEY    | X_ACCESS_TOKEN        |
  | TWITTER_ACCESS_TOKEN_SECRET | X_ACCESS_TOKEN_SECRET |

  So your .env should be:

  TWITTER_ACCESS_TOKEN_KEY='1576789487480356866-h...'
  TWITTER_ACCESS_TOKEN_SECRET='zfl0dsknxnqnfHUy4...'
  TWITTER_API_CONSUMER_KEY='MiWw6GE66b4Nz7fy...'
  TWITTER_API_CONSUMER_SECRET='nniALTBBtdHy...'

  The other keys (X_API_BEARER_TOKEN, X_API_CLIENT_ID, X_API_CLIENT_SECRET, X_USER_ACCESS_TOKEN) are for OAuth 2.0 - crosspost uses OAuth 1.0a so you don't need those.