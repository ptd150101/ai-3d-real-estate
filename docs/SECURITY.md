# Security model

- Passwords use PBKDF2-HMAC-SHA256 with per-user salts and 310,000 iterations.
- API tokens use signed HS256 JWT-compatible payloads with expiration and unique IDs.
- The web BFF stores tokens in HTTP-only, Secure-in-production, SameSite=Lax cookies.
- Admin and agent APIs enforce roles server-side; middleware redirects unauthenticated web users only as a convenience.
- Uploads are basename-normalized, MIME allow-listed and limited to 50 MB.
- Security headers deny framing, sniffing, camera and microphone access.
- Chat rate limiting and prompt-injection markers protect the public assistant.
- Structured logs redact common email and Vietnamese phone patterns.
- Verified/validity metadata gates legal and policy RAG sources.
- Appointment and lead mutations are audited; assistant messages do not silently perform them.

Before production: rotate all seed credentials, use a managed secret store, configure TLS, private buckets/presigned downloads for legal documents, malware scanning, CSP, managed WAF/rate limits and regular restore drills.
