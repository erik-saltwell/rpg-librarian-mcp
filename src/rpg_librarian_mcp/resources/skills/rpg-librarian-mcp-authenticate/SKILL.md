---
name: rpg-librarian-mcp-authenticate
description: Get the user logged into sites the librarian workflow needs a browser session for (e.g. Loot Studios, or any site with no API that requires a login to browse/download from). Use at the start of an organizing session that will touch such sites, or any time a browser-driven fetch comes back access-denied/unauthenticated.
---

# RPG Librarian MCP Authenticate

This file was auto-seeded by `rpg-librarian-mcp` the first time it ran in
this directory. It's yours to edit — the site list below is a starting
default for *this* library, not a fixed template. Add a site any time your
workflow needs a login-gated browser session for it.

## Prerequisite

This skill drives a **browser-automation MCP server** (e.g. Playwright
MCP) that must already be configured separately — this project does not
launch or manage a browser itself. If no such tool is available, tell the
user and stop; there's nothing this skill can do without it.

That server should be running in its default **persistent-profile** mode
(not `--isolated`). In persistent mode it keeps one browser profile on
disk, tied to this project, and logins made in it survive across
sessions, restarts, and reboots with no export step. If it's been
configured with `--isolated`, warn the user that logins won't persist and
this workflow will need to be repeated every session.

## Site list (edit to taste)

- RPGGeek — https://rpggeek.com/login
- DriveThruRPG — https://www.drivethrurpg.com/login.php

Add one line per site as you run into ones that need it, e.g.:

- Loot Studios — https://www.lootstudios.com/login

## When to run this

- At the start of an organizing session that's expected to touch any site
  in the list above (e.g. checking Loot Studios for new STL drops).
- Any time a browser-driven fetch elsewhere in the workflow comes back
  access-denied or otherwise indicates the session isn't logged in. In
  that case, focus on just the specific site that failed rather than the
  whole list.

## Workflow

1. Decide which sites need attention: the full list (session start) or
   just the one that came back access-denied (reactive trigger).
2. Using the browser-automation MCP server's own tools, open one tab per
   site, navigated to its login URL.
3. Tell the user which sites you've opened tabs for and ask them to log
   into each one, then let you know when they're done.
4. Wait for the user's confirmation. Do not attempt to fill in credentials
   or automate the login yourself — the user logs in by hand.
5. Once confirmed, continue with the rest of the workflow. Nothing further
   needs to be saved or exported — the browser-automation server's
   persistent profile already holds the session.
