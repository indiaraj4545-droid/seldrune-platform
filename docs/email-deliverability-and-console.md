# Seldrune Mail: Zoho connection and spam troubleshooting

Mail sent from `@seldrune.in` was reaching Gmail Spam because the tested messages had no SPF or DKIM pass and failed DMARC under the domain's quarantine policy. Keep DMARC in place. Correct SPF and DKIM for the Zoho sender so new messages authenticate and align with the From address.

## Configure the Zoho connection

1. Apply database migration `0054_zoho_mail_connection` with the normal Alembic upgrade process.
2. In the Zoho API Console, register a server-based OAuth client. Add this exact redirect URI, using the deployed Seldrune URL:

   ```text
   https://<seldrune-host>/api/v1/mail/zoho/oauth/callback
   ```

3. Set `SELDRUNE_ZOHO_MAIL_CLIENT_ID`, `SELDRUNE_ZOHO_MAIL_CLIENT_SECRET`, and `SELDRUNE_ZOHO_MAIL_DATA_CENTER=in` in the Seldrune server environment. The configured public application URL must match the deployed host in the redirect URI. Do not expose these values in the browser or commit them.
4. Deploy the application. Sign in to Seldrune and open **Mail** from the console. Under **Domains & access**, connect the Zoho account whose address matches the Seldrune mailbox.

The console reads Inbox and Sent through Zoho's Mail API. It stores OAuth tokens encrypted on the server. IMAP is not used. Drafts remain encrypted in Seldrune until sent.

## Publish sender authentication in DNS

1. In **Mail → Domains & access**, choose **Generate DKIM record**. Add the displayed TXT record in the DNS provider for `seldrune.in`. Use the exact record name and value shown by Zoho; do not regenerate the key after publishing it.
2. Ensure the root domain has a single SPF TXT record authorizing Zoho. If Zoho is the only sender, the value is:

   ```text
   v=spf1 include:zohomail.com ~all
   ```

   If another service already sends as `@seldrune.in`, keep its SPF mechanism and add Zoho's `include:zohomail.com` to that same record. A domain must not publish multiple SPF records.
3. After DNS has propagated, return to Seldrune and choose **Verify SPF and DKIM**. The console asks Zoho to verify both records. Sending remains disabled until both report verified and DKIM is enabled.
4. Send a new test message to Gmail and inspect its original headers. Confirm `spf=pass`, `dkim=pass` with `header.d=seldrune.in`, and `dmarc=pass` with `header.from=seldrune.in`. Previously quarantined messages will not be reprocessed automatically; test with a new message.

The implementation does not change or weaken the domain's DMARC policy. A live Zoho OAuth client and DNS changes are deployment/account configuration and must be completed for the connection and records to take effect.
