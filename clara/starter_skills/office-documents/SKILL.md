---
name: office-documents
description: Create or inspect Word documents, PowerPoint presentations, Excel workbooks and PDFs using installed Python tools, then return a verified artifact.
---
Use the environment tool for the actual Python executable. Installed imports: `docx` for Word, `pptx` for PowerPoint, `openpyxl` for Excel, and `pypdf` for PDF reading/merging. Use write_text to create a script, then run_command to execute it. Put outputs in `outputs/<job-id>/`.

For presentations, choose a clear argument and useful slide structure, use consistent typography and ensure all text fits. For spreadsheets, preserve formulas and distinguish assumptions from observed values. For PDFs, inspect numbered pages and acknowledge when scans require OCR. Do not claim to visually inspect or calculate anything that tools have not actually verified.

Reopen the generated file with its library, verify the expected paragraphs/slides/sheets exist and inspect relevant values. Publish the actual file. Current libraries do not provide a full Office renderer; report that visual or formula-recalculation checks remain pending where relevant.
