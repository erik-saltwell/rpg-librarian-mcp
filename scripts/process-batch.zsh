rpg-librarian quick-dedupe --root /phinneas/rpg/inbox ||
  print -u2 -- "quick-dedupe did not complete; continuing with the normal scan."
rpg-librarian scan --root /phinneas/rpg/inbox
rpg-librarian find-packs --root /phinneas/rpg/inbox
rpg-librarian enrich
claude -p "/process-batch"
rpg-librarian reorganize
claude "/review-items"
