# Security policy

VideoHALO's public runtime is intentionally credential-free. Deployment values
must be supplied through environment variables or Application Default
Credentials (ADC).

## Credential rules

- Do not commit `.env`, ADC files, service-account JSON files, API keys, access
  tokens, private keys, bucket names, project identifiers, or signed URLs.
- The production runtime rejects `GEMINI_API_KEY` and `GOOGLE_API_KEY`.
- Long-lived service-account key files are forbidden. Use user ADC,
  service-account impersonation, or an attached Google Cloud identity.
- Source video objects must remain private and in the approved project.
- Runtime logs, status files, selections, media, and generated dataset records
  are excluded by `.gitignore`.

Before publishing changes, run the tests and scan tracked files for common
credential patterns. If a credential is ever committed, revoke it immediately
and remove it from Git history; deleting it in a later commit is insufficient.

