# Security Policy

## Scope

This policy covers the BR-no-GTA repository, its GitHub Actions workflows, agent/Harness authorization boundaries, dependency and supply-chain configuration, publication paths, Telegram delivery, and private owner-voice handling.

## Reporting a vulnerability

Use GitHub **Private Vulnerability Reporting** for vulnerabilities that could expose credentials, private owner material, authorization boundaries, publication controls, or supply-chain execution.

Do not open a public Issue, Discussion, pull request, workflow log, or artifact containing vulnerability exploitation details, secret values, private keys, tokens, passwords, OAuth refresh tokens, private owner-voice references, or other sensitive evidence.

If Private Vulnerability Reporting is temporarily unavailable, contact the repository owner through a private channel and provide only the minimum information needed to establish a private disclosure path.

## Sensitive material

Never include credential values, secret values, private-key bytes, Telegram bot tokens, provider API keys, OAuth refresh tokens, or raw private owner-voice audio in reports. Public-key fingerprints, content digests, affected paths, redacted scanner identifiers, and sanitized reproduction metadata are preferred evidence.

## Handling

Security findings are evidence for the DeepSeek Harness security disposition. The BR Security Guardian is a read-only independent reviewer and cannot push, merge, publish, deploy, change permissions, rotate credentials, approve itself, or implement its own remediation.

Confirmed credential exposure requires containment and credential revocation or rotation before the affected mutation path resumes.
