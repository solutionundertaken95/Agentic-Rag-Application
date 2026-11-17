# IT Support — Security Incident Response Runbook (RESTRICTED — Security Admin Only)

**Document ID:** SEC-IR-2024-03 | **Department:** SECURITY | **Classification:** Restricted

## Incident Severity Levels

- **S1 (Critical):** Active ransomware, data exfiltration, domain-controller compromise. Response: immediate war room, page on-call Security Admin.
- **S2 (High):** Malware on endpoint, phishing campaign hitting multiple users, suspicious privileged login.
- **S3 (Medium):** Single-user phishing report, policy violation, isolated reconnaissance attempt.

## Containment Steps (S1/S2)

1. Isolate affected hosts from the network via EDR — do not power off (preserves memory evidence).
2. Revoke suspect sessions and reset credentials for affected accounts.
3. Preserve logs: export firewall, VPN, EDR and identity-provider logs to the evidence bucket.
4. Notify the Security Admin on-call and open an incident ticket with severity label.
5. Escalation: security-hotline@company.com / +1-555-0199 (24/7).

## Credential & Key Handling

- Internal credentials, API secrets and key material referenced in this runbook are stored in the
  enterprise vault. Access requires Security Admin role approval — never store secrets in tickets.

## Reporting

- All incidents are reported to the regulator within 72 hours by the Security Admin only.
- Employees must NOT discuss active incidents externally; all communication goes through Security Admin.
