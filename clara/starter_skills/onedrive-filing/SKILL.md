---
name: onedrive-filing
description: "File a finished T1 package into the client's OneDrive folder: find the existing client folder without ever creating a duplicate, create the year's package folder, upload every document, and record what the portal needs. Sharing the folder with the client is a person's step, not Clara's."
---

# OneDrive filing for a T1 package

Use this with the assigned closeout and the TaxPrep or ProFile skill once every PDF is printed and verified. The client never receives the return as attachments: they receive a link to a OneDrive folder shared view-only, and that link becomes the closeout's Drive Link.

**Clara files and uploads. Clara does not share.** The share dialog is the one screen in this system where a wrong setting emails a client their tax documents, and nobody has yet watched it operate. Until a person has, create the folder, upload the package, record the folder and its contents, and hand the sharing step to the staff member who reviews the closeout. State plainly in the handoff that the folder still has to be shared view-only before the email goes out. Filing without sharing is a useful, complete piece of work; guessing at a share dialog is not.

## Account and location

| | |
|---|---|
| Clara's account | `claraagent@clearhouse.ca` — no dot in `claraagent` |
| Host | `clearhouse-my.sharepoint.com` |
| Share root | `/personal/laureen_clearhouse_ca/Documents/CH Clients Share` |

The `-my` host is a **personal** OneDrive: Laureen shared *CH Clients Share* out of her own. It is not a site library, so nothing under `clearhouse.sharepoint.com/sites/...` belongs to this flow. If the closeout's `onedrive_rules` name a different root, that policy wins over this default; otherwise use the root above.

Navigate by URL rather than by clicking through the tree:

```
https://{host}/personal/{owner}/_layouts/15/onedrive.aspx?id={path}&ga=1
```

`{path}` is the server-relative path, URL-encoded as a whole: spaces become `%20`, `/` becomes `%2F`, `_` is left alone. This is an ordinary route, not a hash route, so no page reload is needed after changing it.

**Check you are signed in, and signed in as yourself, every run.** Signed in shows `Create or upload` and an account-manager button whose label carries the display name. Read that name: it proves the session is Clara's and not a colleague's left open in the same profile. Signed out shows `Sign in`, `Pick an account` or `Enter password`; stop and ask rather than attempting to authenticate.

## Selector discipline

**Never select by CSS class.** OneDrive's classes are build-generated hashes: the search box carried `VHvmmNt2vVrKJb47LhAFLw==` on the day of the recon, and Microsoft's next deploy will change it. A class-based selector fails silently, which is worse than failing loudly.

Select by `data-automationid`, then `role`, then `aria-label`, in that order.

| Control | Selector |
|---|---|
| Create or upload | `button[data-automationid=AddNew]` |
| Share | `button[data-automationid=shareCommand]` |
| Copy link | `button[data-automationid=copyLinkCommand]` |
| Manage access | `button[data-automationid=manageAccess]` |
| Breadcrumb | `button[data-automationid=breadcrumb-crumb]` |
| Search box | `input[type=search]`, aria-label `Search box. Suggestions appear as you type` |
| Selection checkbox | `input[data-automationid=selection-checkbox]` |

Reading any of these is safe. Pressing create or upload is ordinary work. Pressing share is not yours to press.

### Three traps in the file grid

1. **A row's name has no stable attribute.** Every `FieldRenderer-name` and `[data-automationid=name]` probe came back empty. What works is the row's own `innerText`, whose **first line** is the item name, as in `"2\nMarch 27\nRadhika Sheth\n90 items\nShared"`.
2. **The first row is the column header**, reading `"Name\nModified\nModified By\nFile size\nSharing\nActivity"`. Skip it. Treating it as an item is the same mistake as reading the first row of a member list as a person.
3. **The grid is virtualised.** Rows outside the viewport are not in the page at all. Scroll, or use search, before concluding anything is absent. Concluding "not there" from an unscrolled grid is how a duplicate client folder gets created.

Search settles in about 6 seconds. Wait for it rather than reading a half-drawn result.

## Where client folders live

```
CH Clients Share
  └── ZZ T1 clients              sorted to the bottom on purpose
        └── {letter bucket}      first letter of the FOLDER NAME, not the surname
              └── {client folder}
                    └── {Year} T1 Package
```

The letter bucket follows the folder name: *Erica Rocchi and Carlos Melo* is filed under **E**, not R. Use letter folders that already exist on screen, and never create a new top-level or letter folder.

## Finding the client folder, and the duplicate trap

**This is the most dangerous step in the whole flow.** Client folder names do not match the wording of the email subject, and searching for the subject's version will miss a folder that exists:

| Source | Value |
|---|---|
| Email subject | `2025 T1 Package - Jeffrey William Langlet & Janice Kyong Chung` |
| Folder actually on disk | `Jeff Langlet and Janice Chung` |

Short first names, and the word `and` rather than `&`. The only other couple folder on record is `Erica Rocchi and Carlos Melo`, whose subject would render with `&`. A single failed exact search therefore proves nothing.

Search for more than one spelling before drawing any conclusion: the full names from the closeout, the short or familiar forms, `and` in place of `&`, each member's surname on its own, and the company name if the client is also a corporate client, because a person may be filed under the company's letter. Then decide:

| What search found | What to do |
|---|---|
| Exactly one exact match | Use it |
| Nothing, after trying every spelling above and scrolling | Create the client folder in the correct letter bucket. A first year is ordinary |
| Near-misses only | **Stop and ask.** Filing this year's return into last year's spouse's folder is not recoverable |
| Two folders with the same name | **Stop and ask.** Never guess between them |

Never merge, rename or move an existing client folder.

## The package folder and the upload

1. Inside the client's folder, create `{Year} T1 Package` for the closeout's tax year, for example `2025 T1 Package`. If a folder for this year already exists, use it rather than making a second one.
2. Upload every document from the verified local package: each member's client copy, T183 and engagement letter, plus any conditional form this return produced, such as instalments or a T1135.
3. **Work out the expected file list from the closeout before you upload, then confirm what actually landed matches it.** Two members with nothing conditional means six files, three per member. One member means three. Do not carry a fixed number in your head.
4. **Clara's packages contain no invoice.** Laureen raises invoices by hand, so a file count taken from an older procedure that includes one will be wrong by exactly one file. Do not upload an invoice and do not wait for one.
5. Log the file names and the count.

Names follow the firm's convention, which is the same one the printing skills use: `{Year} T1 - {Full name}`, `{Year} T183 - {Full name}`, `{Year} Engagement Letter - {Full name}`, and instalments at `{ReturnYear+1} Instalments - {Full name}`. Copy client names from the closeout rather than retyping them. A name may never end in a period: tidy a trailing period rather than refusing the name, which comes up with corporate names ending in `Inc.`. Never put a SIN, an amount, or words like FINAL, v2 or copy into a file name.

## Sharing: what to hand over

Do not open the share dialog. In the handoff, record what the reviewer needs to finish the job: the folder's location and link, the file list you uploaded, the client email addresses from the closeout, and the settings the firm requires, which are **People you choose**, **Can view**, with the **notification turned off**, on the **package folder for this year** and never on the client's main folder. A client folder can hold several years side by side, so sharing the main folder would hand a client other years of their own returns, and in a corporate folder somebody else's entirely.

If a future task explicitly authorizes Clara to share, with a person watching, these are the rules that apply and none of them is optional. Audience is People you choose, never Anyone with the link. Permission is Can view, never Can edit. The notification to the client is turned off **and read back as off** before anything is applied; a dialog that would email the client is a hard stop. All three settings are read back after applying and refused if any is not what was set. After Copy link, wait for the spinner to stop before reading the clipboard: an empty clipboard is a stop, not an empty drive link, and a link identical to the previous one means the clipboard still holds the **previous client's** link, which is a perfectly valid URL for the wrong client.

**One deliberate exception to the rule against touching anything labelled send, email or notify.** The control that stops OneDrive emailing the client is itself called something like *Notify people*. Refusing it on the strength of its name would leave the notification switched on, which is the exact outcome that rule exists to prevent. Turning that one named control off is allowed, and only after reading it back as off. Everything else matching send, email, notify, delete, remove, rename, move to, stop sharing, anyone with the link or can edit stays refused.

## Refusals

- A client folder name is never invented. It comes from the closeout, and a failed search is never proof the folder is absent.
- Near-misses, or two identically named folders, stop the run.
- Never create a top-level or letter folder, and never rename, move or delete anything that already exists.
- Never share, and never operate a share dialog, without explicit authorization for that run.
- A malformed client email address stops the run rather than being silently dropped, which would share with fewer people than the closeout names.
- Client documents go only to the folder this closeout names.

## What to record

Keep a Chrome readback from this attempt showing the folder ID, the folder link, and for every file its ID, exact name and exact byte size. The portal's delivery record needs those, with each file's `member_id` from the assignment, its `document_type` as `client_copy`, `t183`, `engagement_letter`, `instalments` or `t1135`, and the assignment's tax year. Reserve the folder with `reserve_external_write` under the assignment's canonical `storage create_folder` key before creating it, and let `record_portal_delivery` reconcile the reservation. The closeout's own skill carries the rest of that contract.

## Still open: ask, never guess

These have not been settled, and a confident guess at any of them creates a real problem in a real client's folder.

1. **How existing client folders spell a couple.** Evidence points to short first names joined by `and`, but it has not been confirmed as a rule. This is the one that creates duplicate folders.
2. **Whether the package folder is `{Year} T1 Package` or carries the client name too.** One record of the real drive shows a bare year folder instead.
3. **Whether the share dialog ever offers to email the client.** Nobody has watched it.
4. **Whether this account may create sharing links at all.** A visible Share button is not the same as the action succeeding, and pressing it makes a real link to real client data.
5. **Which member's name decides the letter bucket** for a couple whose folder does not exist yet.
