#!/usr/bin/env zsh
# Retain the usual inbox; explicit flags below can override this default.
exec rpg-librarian process-batch --root /phinneas/rpg/inbox "$@"
