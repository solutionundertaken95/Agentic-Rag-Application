"""Seed the Action Agent's data: incidents + service desk tickets in MySQL."""
from datetime import datetime, timezone

from app.services.audit import _connect, init_db


SEED_INCIDENTS = [
    ("INC-1001", "VPN gateway unreachable for APAC users", "IT", "resolved", "P2", "2026-10-02T09:15:00Z",
     "Provider failover caused packet loss on the Singapore gateway; traffic re-routed via Mumbai. Gateway restored after vendor patch."),
    ("INC-1002", "Phishing campaign targeting finance team", "SECURITY", "resolved", "P1", "2026-10-11T14:02:00Z",
     "Credential-harvesting emails spoofing the payroll portal. 3 users clicked; accounts reset, MFA re-enrolled, sender domains blocked."),
    ("INC-1003", "Payroll portal slow during pay-run window", "FINANCE", "resolved", "P3", "2026-10-24T18:30:00Z",
     "Database connection pool exhaustion on the 25th. Pool size increased from 20 to 50; no data loss."),
    ("INC-1004", "Laptop encryption compliance drift", "SECURITY", "open", "P2", "2026-11-05T11:00:00Z",
     "14 devices flagged by EDR for missing disk-encryption policy. Owners notified; re-image scheduled."),
    ("INC-1005", "Printer fleet driver crash on Windows 11 24H2", "IT", "open", "P3", "2026-11-12T08:45:00Z",
     "Vendor driver 6.2.1 crashes spooler after patch Tuesday. Workaround: rollback to 6.1.9; vendor fix pending."),
    ("INC-1006", "Duplicate expense submissions in portal", "FINANCE", "open", "P4", "2026-11-14T16:20:00Z",
     "Mobile client retried submissions on flaky network. Dedupe job applied; client fix in next release."),
    ("INC-1007", "MFA push fatigue attack on executive accounts", "SECURITY", "resolved", "P1", "2026-11-15T07:55:00Z",
     "Repeated MFA pushes overnight. Number-matching enforced; conditional access tightened; no compromise confirmed."),
    ("INC-1008", "Onboarding checklist automation failing", "HR", "open", "P3", "2026-11-16T10:10:00Z",
     "Provisioning workflow times out at the badge-request step. Manual fallback in place; workflow fix scheduled."),
]

SEED_TICKETS = [
    ("SDT-5001", "it.user", "Request: software install — Tableau Desktop", "IT", "open", "P3", "it.user",
     "Needs Tableau for Q4 reporting dashboards. Manager approval attached.", "2026-11-15T13:00:00Z"),
    ("SDT-5002", "fin.user", "Expense report missing reimbursement", "FINANCE", "in_progress", "P2", "fin.user",
     "October claim missing $180 meal receipts; Finance investigating duplicate batch.", "2026-11-16T09:30:00Z"),
    ("SDT-5003", "hr.user", "Parental leave portal shows wrong balance", "HR", "open", "P2", "hr.user",
     "Portal shows 4 weeks instead of 18 for primary caregiver; payroll sync issue suspected.", "2026-11-16T15:45:00Z"),
    ("SDT-5004", "secadmin", "Quarterly access review certification", "SECURITY", "resolved", "P1", "secadmin",
     "Q4 privileged-access certification completed; 2 stale accounts revoked.", "2026-11-10T11:20:00Z"),
]


def seed() -> None:
    init_db()  # ensure base schema exists
    con = _connect()
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS incidents (
            incident_ref VARCHAR(32) PRIMARY KEY,
            title TEXT NOT NULL,
            department VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            priority VARCHAR(8) NOT NULL,
            reported_at VARCHAR(64) NOT NULL,
            description LONGTEXT NOT NULL,
            INDEX idx_inc_dept (department)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS service_desk_tickets (
            ticket_ref VARCHAR(32) PRIMARY KEY,
            requester VARCHAR(128) NOT NULL,
            title TEXT NOT NULL,
            department VARCHAR(32) NOT NULL,
            state VARCHAR(32) NOT NULL,
            priority VARCHAR(8) NOT NULL,
            assignee VARCHAR(128),
            description LONGTEXT NOT NULL,
            created_at VARCHAR(64) NOT NULL,
            INDEX idx_sdt_requester (requester)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS pending_actions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            action_ref VARCHAR(32) NOT NULL UNIQUE,
            created_at VARCHAR(64) NOT NULL,
            username VARCHAR(128) NOT NULL,
            roles TEXT NOT NULL,
            tool_name VARCHAR(64) NOT NULL,
            arguments_json LONGTEXT NOT NULL,
            department VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending_approval',
            resolution VARCHAR(32) DEFAULT NULL,
            reviewer VARCHAR(128) DEFAULT NULL,
            reviewer_comment TEXT,
            resolved_at VARCHAR(64) DEFAULT NULL,
            execution_result LONGTEXT,
            INDEX idx_pa_status (status)
        )"""
    )
    con.commit()

    cur.execute("SELECT COUNT(*) FROM incidents")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO incidents(incident_ref, title, department, status, priority, reported_at, description)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
            SEED_INCIDENTS,
        )
    cur.execute("SELECT COUNT(*) FROM service_desk_tickets")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO service_desk_tickets(ticket_ref, requester, title, department, state, priority, assignee, description, created_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            SEED_TICKETS,
        )
    con.commit()
    cur.close()
    con.close()
    print(f"Seeded {len(SEED_INCIDENTS)} incidents, {len(SEED_TICKETS)} service desk tickets.")


if __name__ == "__main__":
    seed()
