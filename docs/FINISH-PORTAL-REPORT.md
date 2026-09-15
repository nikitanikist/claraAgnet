# Finish an existing T1 portal report

Use this only when TaxPrep, PandaDoc and OneDrive work has finished and the final
portal result was not acknowledged. Preserve the original task and its output.
This command sends links and metadata, not PDFs. It runs no model or desktop task.

1. Confirm the original local task is terminal and no other task is active. Stop
   the Clara service normally with Ctrl+C in its own console. Install the reviewed
   integration revision with the existing backup/update procedure.
2. From that installation, check the exact job, attempt and fence:

   ```powershell
   .\Finish-ClaraPortalReport.ps1 -JobId '<portal-job-uuid>' -Attempt <number> -Fence <number>
   ```

   The default checks saved evidence and measured usage locally; it sends no
   network requests. Keep any reported missing evidence for review.
3. The portal administrator must authorize reporting for this exact expired
   attempt through the guarded report-authorization routine. Execution remains
   disabled. Do not reset the job, renew its execution lease or enable new claims.
4. Add `-Send` to the same command. It submits the saved links and usage through
   normal portal verification. Only a receipt with `handoff.status=ready_to_email`
   confirms the handoff. `needs_review` identifies remaining verification work.
   If the receipt is lost, retry this same command; never delete or edit its
   journal record or create a new closeout.
5. Start Clara normally to report current desktop quiescence. Confirm the portal
   released the original worker hold and Laureen can see the prepared draft and
   links. Nothing in this procedure sends the email or performs invoicing.

The existing encrypted worker credential is loaded through Clara's standard
process wrapper. Do not paste credentials into commands or diagnostics.
