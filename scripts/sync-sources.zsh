#!/usr/bin/env zsh
# One-shot nightly ingestion; configure the catalog via --catalog or environment.
exec rpg-librarian sync-sources --inbox /phinneas/rpg/inbox "$@"
