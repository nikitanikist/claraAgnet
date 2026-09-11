---
name: computer-navigation
description: Work in an unfamiliar browser or Windows application using live DOM, accessibility information and screenshots, including popups and moved controls.
---
Use direct file tools for file tasks. For browser tasks, inspect current pages and an accessibility snapshot before acting. Clara's browser connector uses its own Chrome profile; a missing website session means the user needs to sign in there. Do not assume the ordinary Chrome window shares that login.

For native Windows work, inspect the current application and its UIA tree/screenshot. Open applications by discovered name or executable, inspect their actual controls, and choose actions based on their labels and current state. Prefer stable accessible elements; use coordinates only from a fresh screenshot of the correct window.

After each significant action inspect the resulting state. Read popup contents before choosing whether to dismiss them. Do not dismiss warnings that indicate data loss, client mismatch or submission consequences merely to continue. A timeout is not evidence an action failed: inspect for an existing result before retrying uploads or document creation.

If the desktop is locked, inaccessible, or showing a different session, stop and ask the user to restore the session. Keep task state and explain the last verified action. Do not change Windows session security settings to work around it.
