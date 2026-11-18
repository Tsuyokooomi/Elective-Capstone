# VPN Connection Troubleshooting
SOP ID: KB-008
Category: Network and Email
Applies to: Employees who cannot connect to CapstoneVPN or whose connection drops.
Action: create_ticket if steps fail
Escalation: After two failed fixes.

Steps:
1. Confirm that your internet works. Open a public website.
2. Restart CapstoneVPN and try again.
3. Match the error to a fix:
   - "Authentication failed": check your password and MFA code. If your account is locked, see KB-002.
   - "Cannot reach server": your network may block VPN traffic. Try another network, such as a phone hotspot.
   - Connection drops often: move closer to your router, or use a cable.
4. Check that your laptop's date and time are set to automatic.
5. Restart your laptop.
6. Uninstall and reinstall CapstoneVPN from Software Center.

Collect before you ask for help: the exact error message, the time it happened, and your network type (home, hotspot, public).

Escalate to a human if: the problem remains after steps 1 to 6.

Related SOPs: KB-002, KB-007, KB-009
