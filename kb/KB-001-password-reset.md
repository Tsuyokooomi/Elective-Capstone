# Password Reset (Self-Service)
SOP ID: KB-001
Category: Accounts and Access
Applies to: All CapstoneCompany employees with a work account.
Action: reset_password
Escalation: Only if the steps below fail.

Steps:
1. Open the self-service portal at selfservice.capstonecompany.example.
2. Select "Forgot password".
3. Enter your work email address.
4. Approve the sign-in request with your MFA code (see KB-003).
5. Create a new password that meets the password policy (see KB-020).
6. Sign in with the new password on your laptop.
7. Update the saved password on your phone's mail app, or the phone will keep trying the old one and lock your account (see KB-002).

Notes:
- The reset link is valid for 15 minutes.
- The helpdesk assistant can start a reset after it confirms your employee ID and MFA code. It never sends a password in chat.

Escalate to a human if: you cannot use your MFA device (see KB-004), your account is locked (see KB-002), or the reset fails three times.

Related SOPs: KB-002, KB-003, KB-004, KB-020
