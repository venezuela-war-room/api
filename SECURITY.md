# Security Policy

This API may process sensitive disaster-relief data. Please report security and privacy issues privately.

## Reporting a vulnerability

Email: [jesusareyesv.ve@gmail.com](mailto:jesusareyesv.ve@gmail.com)

Please include:

- A clear description of the issue.
- Steps to reproduce, if safe to share.
- Affected endpoints, models, migrations, scripts, or deployment configuration.
- Potential impact and suggested mitigation, if known.

Do **not** open public issues for vulnerabilities, leaked secrets, authorization bypasses, ingestion abuse, CORS mistakes, database exposure, or personal-data leaks.

## Examples to report privately

- Exposure of API keys, master keys, database credentials, or Railway secrets.
- Authentication/authorization bypass for protected or master-admin endpoints.
- Public access to personal data beyond the intended API contract.
- SQL injection, unsafe raw SQL, or migration/data-loss risks.
- Abuse paths that allow mass scraping, spam ingestion, destructive updates, or source spoofing.
- Logs or analytics that include sensitive personal data.

## Safe testing

Use local or synthetic data only. Do not test against real people’s data or production infrastructure without explicit maintainer permission.
