rpg-librarian scan --root /phinneas/rpg/inbox
rpg-librarian find-packs --root /phinneas/rpg/inbox
rpg-librarian enrich
claude -p "/process-batch"
rpg-librarian reorganize
claude "/review-items"
