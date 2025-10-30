# Security Policy

The HuntStand Membership Exporter is currently in **beta (v0.x)**. During this phase we:

- Respond to security issues on a **best-effort** basis.
- May introduce breaking changes between minor `0.x` versions.
- Encourage users to stay on the latest release (no parallel support branches yet).

## Supported Versions

| Version   | Supported | Notes |
|-----------|-----------|-------|
| 0.1.x     | ✅        | Latest beta; please upgrade promptly. |
| < 0.1.0   | ❌        | Pre-release / unpublished builds. |

Once the project reaches `1.0.0`, a clearer support window (e.g. last two minor versions) will be defined.

## Reporting a Vulnerability

Please create a **private issue** or email the maintainer if sensitive. For now, open a GitHub Issue and prepend the title with `[SECURITY]`.

Include (sanitize any sensitive data):

1. Affected version (`huntstand-exporter --version` coming soon; for now cite tag or commit SHA).
2. Description of the issue and potential impact.
3. Reproduction steps (minimal inputs, no real cookie values).
4. Suggested remediation if you have one.

We will acknowledge within **5 business days**. If confirmed:

- A fix branch will be created and linked.
- A patched release will be published; you may be credited unless you request anonymity.

## Scope

Security concerns include (non-exhaustive):

- Leakage of authentication cookies or credentials.
- Exporting or logging private member data in unintended places.
- Vulnerabilities leading to unauthorized HuntStand API access.

Out of scope:

- Rate limiting responses from HuntStand.
- API schema changes by HuntStand (compatibility issues).

## Responsible Use

Do not share real cookies or personal data in issues or pull requests. Use placeholders like `SESSIONID123`.

## Future Plans

- Add `--dry-run` mode to validate auth without data export.
- Add a security contact email.
- Provide a signed release process.
