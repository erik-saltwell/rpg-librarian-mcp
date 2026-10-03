"""`find-packs`: identify packs from folder evidence, a folder-name search, and an LLM.

`evidence` builds the folder tree and its deterministic facts from the catalog alone
(no filesystem walk); `judge` asks the model about a batch of sibling folders. The
command in `commands/find_packs.py` walks the tree top-down and forms the packs.
"""
