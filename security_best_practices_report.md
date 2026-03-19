# Security Best Practices Report

## Executive Summary

The most serious issues in this codebase are concentrated around trust boundaries: token verification, admin authorization, unauthenticated secret-management endpoints, and server-side callback handling. In the current state, an attacker could gain authenticated access with a token from the wrong Clerk tenant if `CLERK_ISSUER` is unset, become an admin if the admin allowlist is not configured, overwrite shared AI and YouTube configuration without authentication, and coerce the backend into POSTing to attacker-chosen URLs.

## Critical Findings

### S-001
- Rule ID: FASTAPI-AUTH-001
- Severity: Critical
- Location: [backend/clerk_auth.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/clerk_auth.py):40, [backend/clerk_auth.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/clerk_auth.py):113
- Evidence:
```python
def _require_allowed_issuer(claimed_issuer: str) -> str:
    configured = os.environ.get("CLERK_ISSUER", "").strip().rstrip("/")
    ...
    if configured:
        ...
        return configured

    parsed = urlparse(normalized_claim)
    ...
    if "clerk" not in parsed.netloc.lower():
        raise HTTPException(status_code=401, detail="Token issuer is not an allowed Clerk issuer.")
    return normalized_claim
```
- Impact: If `CLERK_ISSUER` is missing in deployment, any token signed by any Clerk tenant can be accepted as long as its issuer hostname contains `clerk`. That allows unauthorized users from a different Clerk instance to access authenticated routes.
- Fix: Fail closed when `CLERK_ISSUER` is not configured and only accept tokens whose `iss` exactly matches that configured issuer.
- Mitigation: Also consider setting and validating `CLERK_AUDIENCE` for additional token scoping.
- False positive notes: If infrastructure guarantees `CLERK_ISSUER` is always set, exploitation risk drops, but that guarantee is not enforced in app code today.

### S-002
- Rule ID: FASTAPI-AUTH-001
- Severity: Critical
- Location: [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):1507, [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):1532, [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):1600
- Evidence:
```python
@app.get("/ai/config")
async def get_ai_config():
    ...

@app.post("/ai/config")
async def set_ai_config(request: AIConfigRequest):
    ...
    save_config(merged)

@app.post("/ai/validate")
async def validate_key(request: AIValidateRequest):
    ...
```
- Impact: Any unauthenticated internet user can update shared Gemini, Groq, Firecrawl, and YouTube client settings, disconnect or poison the shared YouTube integration, and trigger outbound validation against arbitrary API keys.
- Fix: Require admin authorization for these routes and keep any public status data on a separate non-sensitive endpoint.
- Mitigation: Audit any already-deployed instances for unexpected `.env.json` changes and rotate shared credentials if tampering is possible.
- False positive notes: This is directly visible in app code and does not depend on infrastructure assumptions.

## High Findings

### S-003
- Rule ID: FASTAPI-AUTH-001
- Severity: High
- Location: [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):345
- Evidence:
```python
def _is_admin_user(user: ClerkUser) -> bool:
    allowed_ids = _split_csv_env("SHORTMAKER_ADMIN_USER_IDS")
    allowed_emails = {item.lower() for item in _split_csv_env("SHORTMAKER_ADMIN_EMAILS")}
    if not allowed_ids and not allowed_emails:
        return True
```
- Impact: If the deployment forgets to set the admin allowlist, every authenticated user automatically becomes an admin and can access secret-management and YouTube publishing routes.
- Fix: Change the default to deny admin access unless an explicit allowlist matches.
- Mitigation: Validate admin env configuration at startup and treat missing admin allowlists as a deployment misconfiguration.
- False positive notes: Only safe if deployment absolutely guarantees the allowlist is always present, which is not enforced today.

### S-004
- Rule ID: FASTAPI-SSRF-001
- Severity: High
- Location: [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):416, [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):519, [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):1301
- Evidence:
```python
def _validate_callback_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="callback_url must be http or https")
```
```python
request = urllib.request.Request(callback_url, data=body, headers=headers, method="POST")
```
- Impact: Any authenticated user can supply a `callback_url` and cause the backend to POST job results to attacker-chosen destinations, including internal services if reachable. This is a classic SSRF primitive.
- Fix: Disable callbacks by default for public users and only permit explicitly allowlisted callback hosts.
- Mitigation: Add outbound egress filtering at the infrastructure layer and block access to cloud metadata/internal control planes.
- False positive notes: Risk remains even if only authenticated users can reach the route; any user account can weaponize it.

## Medium Findings

### S-005
- Rule ID: FASTAPI-OPENAPI-001 / FASTAPI-DEPLOY-003
- Severity: Medium
- Location: [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):92, [backend/main.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/main.py):99
- Evidence:
```python
app = FastAPI(
    title="ShortMaker",
    description="Convert long-form videos into short vertical clips with AI",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
```
- Impact: Production docs remain enabled by default and CORS is fully permissive. This increases attack surface discovery and broadens browser-based access beyond the intended frontend origin.
- Fix: Disable public docs in production, add trusted host validation, and restrict CORS to known origins.
- Mitigation: Verify equivalent controls at the edge if these settings are intentionally broad during development.
- False positive notes: CORS alone is not auth bypass, but it is too permissive for production.

### S-006
- Rule ID: REACT-CONFIG-001 / FASTAPI-SECRETS-001
- Severity: Medium
- Location: [backend/ai_engine.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/ai_engine.py):30, [backend/ai_engine.py](/C:/Users/Ashmil%20P/Desktop/shortmaker/backend/ai_engine.py):58
- Evidence:
```python
CONFIG_FILE = BASE_DIR / ".env.json"
...
with open(CONFIG_FILE, 'w') as f:
    json.dump(config, f, indent=2)
```
- Impact: Shared API keys, YouTube OAuth client secrets, and refresh tokens are stored in plaintext on disk. A filesystem compromise, backup leak, or accidental exposure reveals all of them at once.
- Fix: Prefer environment-managed secrets for deployment and minimize writing long-lived credentials to disk.
- Mitigation: If file storage must remain, restrict file permissions and rotate credentials on suspicion of host compromise.
- False positive notes: This is not a direct remote exploit by itself, but it materially increases breach impact.
