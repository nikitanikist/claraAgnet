---
name: onedrive-filing
description: "File a finished T1 package into the client's OneDrive folder: find the existing client folder without ever creating a duplicate, create the year's package folder, upload every document, share it view-only with Copy link and never Send, and record what the portal needs."
---

# OneDrive filing for a T1 package

Use this with the assigned closeout and the TaxPrep or ProFile skill once every PDF is printed and verified. The client never receives the return as attachments: they receive a link to a OneDrive folder shared view-only, and that link becomes the closeout's Drive Link.

The share dialog is the one screen in this whole system where a wrong press emails a client their tax documents, because its blue primary button is **Send**. Laureen has now shown that screen and given the rule: use **Copy link**, never Send. That rule is absolute and appears again in full below. Everything else here exists to put the right folder in front of that dialog before it is opened.

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

Reading any of these is safe. Create, upload and share are ordinary work here; what is never ordinary is the Send button inside the share dialog.

### Three traps in the file grid

1. **A row's name has no stable attribute.** Every `FieldRenderer-name` and `[data-automationid=name]` probe came back empty. What works is the row's own `innerText`, whose **first line** is the item name, as in `"2\nMarch 27\nRadhika Sheth\n90 items\nShared"`.
2. **The first row is the column header**, reading `"Name\nModified\nModified By\nFile size\nSharing\nActivity"`. Skip it. Treating it as an item is the same mistake as reading the first row of a member list as a person.
3. **The grid is virtualised.** Rows outside the viewport are not in the page at all. Scroll, or use search, before concluding anything is absent. Concluding "not there" from an unscrolled grid is how a duplicate client folder gets created.

Search settles in about 6 seconds. Wait for it rather than reading a half-drawn result.

## Where client folders live

```
CH Clients Share
  └── ZZ T1 Clients
        └── {letter bucket}
              └── {client folder}                          e.g. Adam and Jennifer Pink
                    ├── 2024 T1 Package - Adam & Jennifer Pink
                    └── 2025 T1 Package - Adam & Jennifer Pink
```

**Every year's package sits directly inside the client folder. There is no year folder in between** (Laureen, 17 September 2026). The E drive is arranged differently, with a year folder in the path, and that structure does not carry over here. If you are thinking of creating a folder called `2025`, you have the wrong tree in mind.

**The letter bucket only decides where to CREATE a folder, never where to look for one.** If the client already has a folder, use it wherever it sits. The two trees legitimately differ: Vikram Karwal is filed on the E drive under T as `Trimaxx - Vikram Karwal`, while his client-share folder is under V as `Vikram Karwal`, and Laureen confirmed that is correct (17 September 2026). Clara found it by searching and reused it, which is exactly right. Only when no folder exists anywhere does the E drive filing decide the bucket for the new one. Use letter folders that already exist; never create a new top-level or letter folder.

## Finding the client folder, and the duplicate trap

**This is the most dangerous step in the whole flow, and the reason is that there is no naming standard to rely on.** Laureen: *"I would usually just search for one name — there was no standard when we started using it so it could be any way."* The firm's own folders prove it. One real client folder holds these four packages, filed by three different people:

```
2022 T1 Package - Adam and Jennifer Pink
2023 T1 Package - Jennifer and Adam Pink      names in the other order
2024 T1 Package - Adam & Jennifer Pink        ampersand instead of and
2025 T1 Package - Adam & Jennifer Pink
```

So **search the way Laureen does: one name at a time.** A surname is usually the most distinctive. Searching the full couple string as the closeout writes it is the one approach that reliably finds nothing, because almost no folder is spelled that way. Search one member's surname, then the other's, then a first name, and the company name if the client is also a corporate client, since a person may be filed under the company's letter. Read the results with your eyes rather than matching strings: you are looking for the folder that is plainly this client.

The E drive filing is a useful hint for what to search for, since the client is already filed there under some form of their name or their company's. It does not tell you where the client-share folder is: only the search does.

| What the searches found | What to do |
|---|---|
| A folder that is plainly this client | Use it, whatever its spelling |
| Nothing, after searching each name separately and scrolling | Create the client folder, in the bucket the E drive filing indicates. A first year is ordinary |
| Two or more that could each be this client | **Stop and ask.** Filing this year's return into the wrong one is not recoverable |

Never merge, rename or move an existing client folder, and never "correct" a folder whose spelling differs from this year's closeout. The spelling varying is normal here, not a mistake to fix.

## The package folder and the upload

1. Inside the client's folder, create this year's package folder. The name carries the client too: `{Year} T1 Package - {client names}`, for example `2025 T1 Package - Adam & Jennifer Pink`. If a folder for this year already exists, use it rather than making a second one.

   **Take the spelling from the sibling packages already in that folder.** Copy the most recent year's name and change only the year. Those folders are how this client is actually written here, and following them keeps a client's own folder internally consistent instead of adding a fifth spelling. Only when there is no previous package, a genuine first year, fall back to the client folder's own name.
2. Upload every document from the verified local package: each member's client copy, T183 and engagement letter, plus any conditional form this return produced, such as instalments or a T1135.
3. **Work out the expected file list from the closeout before you upload, then confirm what actually landed matches it.** Two members with nothing conditional means six files, three per member. One member means three. Do not carry a fixed number in your head.
4. **Clara's packages contain no invoice.** Laureen raises invoices by hand, so a file count taken from an older procedure that includes one will be wrong by exactly one file. Do not upload an invoice and do not wait for one.
5. Log the file names and the count.

Names follow the firm's convention, which is the same one the printing skills use: `{Year} T1 - {Full name}`, `{Year} T183 - {Full name}`, `{Year} Engagement Letter - {Full name}`, and instalments at `{ReturnYear+1} Instalments - {Full name}`. Copy client names from the closeout rather than retyping them. A name may never end in a period: tidy a trailing period rather than refusing the name, which comes up with corporate names ending in `Inc.`. Never put a SIN, an amount, or words like FINAL, v2 or copy into a file name.

## Sharing the package folder

The share dialog has now been shown by Laureen, and it holds one specific danger.

```
Share "2025 T1 Pac...nnifer Pink"
  [ Add a name, group, or email        ] [pencil v]
  [ Add a message                      ]
  (avatars)         [ Copy link ]  [gear]  [ > Send ]
```

**The blue button in the bottom-right corner is Send, and pressing it emails the client.** It sits exactly where a confirm button normally sits, which is what makes it dangerous: the instinct to finish a dialog by pressing the prominent blue button is the one instinct that must not be followed here. Laureen's instruction is exact: *"make sure she only uses the Copy Link button and not the Send button."*

**Copy link is the plain button to its left, and it is the only button on this dialog you may press to finish.** Never press Send. Never type anything into *Add a message*, because that box is the body of an email to the client.

Share the **package folder for this year**, never the client's main folder. A client folder holds every year side by side, so sharing the main folder would hand this client their other years as well, and in a corporate folder somebody else's entirely.

1. Select this year's package folder so the dialog names it. Read the dialog title and confirm it is the right folder before touching anything.
2. Open link settings with the gear. Audience is **People you choose**, never *Anyone with the link*. Permission is **Can view**, never *Can edit*. Apply, then read both back and refuse to continue if either is not what you set.
3. Put the client email addresses from the closeout in the name field. There may be more than one, the signing member's address plus any additional addresses the closeout names. A malformed address is a stop, never a silent drop, because sharing with fewer people than the closeout names is invisible afterwards.
4. Press **Copy link**, and wait until the spinner stops before reading the clipboard.
5. Check what you copied. An empty clipboard is a stop, not an empty drive link. A link identical to the previous client's means the clipboard never updated and still holds **that** client's link, which is a perfectly valid URL for entirely the wrong person.
6. Never press Send, at any point, for any reason.

Hold the link in run state and record it with the delivery, so it reaches the portal alongside the PandaDoc links rather than separately.

**The first time this runs on a real client folder, a person should watch it.** Say so in the handoff if nobody has yet. Everything matching delete, remove, rename, move to, stop sharing, anyone with the link or can edit stays refused throughout.

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

Laureen answered most of this on 17 September 2026, and those answers are written into the sections above. Two things remain genuinely unknown.

1. **Whether this account can actually create a sharing link.** A visible Share button is not the same as the action succeeding, and the first attempt makes a real link to real client data. If it refuses, stop and say so rather than working around it.
2. **What the gear's link settings look like in practice.** The audience and permission controls behind it have not been watched, so read back what you set rather than assuming the dialog kept it.

Answered, and not to be re-litigated: couples have no spelling standard, so search one name at a time; the package folder is `{Year} T1 Package - {client names}` and sits directly in the client folder with no year folder; the share dialog does offer to email the client, via the blue Send button, which is why Copy link is the only button you finish with; and the letter bucket follows the client's filing on the E drive.
