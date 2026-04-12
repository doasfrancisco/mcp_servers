# Gmail MCP — Cloud Deployment

Move Gmail MCP from local stdio to an HTTP-reachable cloud service so cloud workers (Signal) can run searches and read messages without the local machine being up.

## Architecture

```
Cloud Signal agent
    │
    │  Authorization: Bearer <token>
    ▼
ECS Express Mode (us-east-1)
    │  https://<service>.ecs.us-east-1.on.aws/mcp
    │
    ├── cloud_server.py (FastMCP HTTP, StaticTokenVerifier)
    ├── server.py tools (unchanged)
    ├── gmail_client.py (unchanged)
    └── auth.py (reads creds from /tmp/gmail/ or local)
```

## Key difference from damelo

Damelo is **multi-user** — each user logs in via GitHub OAuth, tokens stored in DynamoDB. Gmail MCP is **single-user** — it operates on the owner's Gmail accounts (personal/work/university). No user directory needed.

- **Auth**: `StaticTokenVerifier` with one shared secret (`GMAIL_MCP_BEARER_TOKEN`)
- **No middleware**, no db_api roundtrip
- Cloud Signal sends `Authorization: Bearer <token>` on every request

## Credentials bootstrap

### Current layout (local, filesystem)

```
credentials/credentials.json        # Google OAuth client
credentials/token_personal.json     # refresh token per account
credentials/token_work.json
credentials/token_university.json
accounts.json                       # {email, alias} list
```

### Cloud approach

Load from env vars at container startup, write to `/tmp/gmail/credentials/`, let the existing `auth.py` read files unchanged:

```
GMAIL_MCP_BEARER_TOKEN       # static bearer token for Signal auth
GMAIL_CLIENT_SECRETS_JSON    # full credentials.json contents
GMAIL_ACCOUNTS_JSON          # full accounts.json contents
GMAIL_TOKEN_PERSONAL_JSON    # token_personal.json contents
GMAIL_TOKEN_WORK_JSON
GMAIL_TOKEN_UNIVERSITY_JSON
```

Google's library refreshes access tokens in-memory using the long-lived `refresh_token` — on container restart it just re-refreshes. No persistence store needed.

## Code changes

1. **New `cloud_server.py`** — HTTP entry point that:
   - Reads env vars, materializes creds into `/tmp/gmail`
   - Sets `GMAIL_CREDENTIALS_DIR=/tmp/gmail/credentials` and `GMAIL_ACCOUNTS_PATH=/tmp/gmail/accounts.json`
   - Imports the existing tools from `server.py`
   - Wraps with `StaticTokenVerifier`
   - Exposes `app = mcp.http_app()`

2. **Modify `auth.py`** — respect `GMAIL_CREDENTIALS_DIR` env var if set, otherwise keep current behavior (local dev unchanged).

3. **Modify `gmail_client.py`** — respect `GMAIL_ACCOUNTS_PATH` env var similarly.

4. **Modify `server.py`** — skip the `_lifespan` browser setup when `GMAIL_CLOUD_MODE=1`, and make `ctx.elicit()` calls degrade gracefully (hard-error, don't auto-accept — Signal must pass explicit flags if needed).

5. **New `Dockerfile`** — Python 3.13, copy repo, `pip install -r requirements.txt`, uvicorn on 8080. Mirrors damelo.

6. **New `requirements.txt`** — frozen deps (Docker doesn't use uv).

7. **New `push.sh`** — ECR login + build + tag + push to `727646507402.dkr.ecr.us-east-1.amazonaws.com/gmail_mcp:latest`.

8. **New `.dockerignore`** — exclude `credentials/`, `accounts.json`, `logs/`, `__pycache__`, `.venv`.

## Hosting: AWS ECS Express Mode

> App Runner is sunsetting (no new customers after April 30, 2026). ECS Express Mode is AWS's official replacement — same simplicity, same ECR workflow.

### One-time IAM setup

```bash
# Create roles
aws iam create-role --role-name ecsTaskExecutionRole \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'

aws iam create-role --role-name ecsInfrastructureRoleForExpressServices \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowAccessInfrastructureForECSExpressServices",
            "Effect": "Allow",
            "Principal": {"Service": "ecs.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'

# Attach managed policies
aws iam attach-role-policy --role-name ecsTaskExecutionRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

### Deploy

```bash
# 1. Push image to ECR (same push.sh pattern as damelo)
./push.sh

# 2. Create Express Mode service
aws ecs create-express-gateway-service \
    --service-name "gmail-mcp" \
    --primary-container '{
        "image": "727646507402.dkr.ecr.us-east-1.amazonaws.com/gmail_mcp:latest",
        "port": 8080,
        "healthCheck": {"path": "/mcp"},
        "environment": {
            "GMAIL_CLOUD_MODE": "1",
            "GMAIL_MCP_BEARER_TOKEN": "<generate-a-secure-token>",
            "GMAIL_CLIENT_SECRETS_JSON": "<contents-of-credentials.json>",
            "GMAIL_ACCOUNTS_JSON": "<contents-of-accounts.json>",
            "GMAIL_TOKEN_PERSONAL_JSON": "<contents-of-token_personal.json>",
            "GMAIL_TOKEN_WORK_JSON": "<contents-of-token_work.json>",
            "GMAIL_TOKEN_UNIVERSITY_JSON": "<contents-of-token_university.json>"
        }
    }' \
    --compute '{"cpu": "1 vCPU", "memory": "2 GB"}' \
    --auto-scaling '{"minimumTaskCount": 1, "maximumTaskCount": 3}' \
    --execution-role-arn arn:aws:iam::727646507402:role/ecsTaskExecutionRole \
    --infrastructure-role-arn arn:aws:iam::727646507402:role/ecsInfrastructureRoleForExpressServices \
    --monitor-resources

# 3. Access at:
# https://gmail-mcp.ecs.us-east-1.on.aws/mcp
```

### Update (after code changes)

```bash
./push.sh
aws ecs update-express-gateway-service \
    --service-arn arn:aws:ecs:us-east-1:727646507402:service/gmail-mcp \
    --primary-container '{"image": "727646507402.dkr.ecr.us-east-1.amazonaws.com/gmail_mcp:latest"}' \
    --monitor-resources
```

### Register with Claude Code / Signal

```bash
claude mcp add --transport http gmail \
    --header "Authorization: Bearer <token>" \
    https://gmail-mcp.ecs.us-east-1.on.aws/mcp
```

## Decisions

| Question | Decision |
|----------|----------|
| Hosting target | ECS Express Mode (App Runner is sunsetting) |
| Auth | Static bearer token via `StaticTokenVerifier` |
| Credentials storage | Env vars in ECS (encrypted at rest) |
| `ctx.elicit()` in cloud | Hard-error — Signal must not trigger interactive tools |
| Attachment downloads | Skip over HTTP — no filesystem on cloud |
| Setup browser | Skip in cloud mode — fail fast if creds missing |
| `.dockerignore` | Excludes `credentials/`, `accounts.json` — creds come from env only |

## push.sh

```bash
#!/bin/bash
set -e

aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin \
    727646507402.dkr.ecr.us-east-1.amazonaws.com

docker build -t gmail_mcp .
docker tag gmail_mcp:latest 727646507402.dkr.ecr.us-east-1.amazonaws.com/gmail_mcp:latest
docker push 727646507402.dkr.ecr.us-east-1.amazonaws.com/gmail_mcp:latest
```

## Dockerfile

```dockerfile
FROM python:3.13

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "cloud_server:app", "--host", "0.0.0.0", "--port", "8080"]
```
