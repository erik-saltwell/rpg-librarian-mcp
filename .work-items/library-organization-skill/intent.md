# Library organization review skill

## Intended outcome

Approved skill name: **`review-organization`**.

Give the owner a skill they can call to have an LLM review the organization of the catalog, and thus the library, in the manner of a code review. The review concerns relationships between entries, products, product lines, files, and packs.

## Agreed behavior

- **Clear-cut issues:** apply corrections automatically by updating entries' product and product-line assignments or files' pack membership.
- **Judgment calls:** store recommendations in the existing review system, so the owner can consider and resolve them with `review-items`.

These categories distinguish actionable corrections from decisions requiring the owner's judgment. Invoking the skill should authorize its clear-cut corrections; judgment calls are deferred.

## Accepted workshop decisions

Accepted during the workshop completed 2026-10-11:

- **Review related groups together.** Before changing an assignment, examine its current product or pack, the proposed destination, and neighboring entries or members. This supports coherent corrections and helps distinguish fragmented products from meaningful edition or release differences.
- **Remember the owner's decisions.** Respect resolved organization choices rather than repeatedly proposing or undoing them. Reopen a decision only when materially new evidence warrants reconsideration, explaining what changed.
- **Explain every finding.** Record the current organization, proposed organization, affected entries, and supporting evidence. Retain that explanation for applied fixes. Deferred recommendations also include a recommended resolution; group related findings into one coherent decision where appropriate.
- **Continue across invocations.** Track what has been examined and where to resume, so repeated calls progressively cover the library. Changed content can become eligible for review again. Completed coverage means examined, not guaranteed correct.
- **Store memory in the database.** Prior decisions and review continuity state belong in the database for access by later review calls, rather than depending on conversational memory.
- **Apply corrections atomically per related group.** Validate the affected relationships, then commit the complete catalog correction or leave the group unchanged with a review item. Product assignment and pack membership changes must not leave a partially applied organization.
- **Return an invocation receipt.** Summarize what was examined, changed, deferred, and where the next call will resume. Link applied changes to their stored explanations and deferred findings to their review items. Group related changes and summarize uneventful coverage.

## Existing integration inspected

The bundled [review-items skill](../../apps/rpg-librarian/src/rpg_librarian/resources/skills/review-items/SKILL.md) reports open entry review flags and supports product and pack corrections after the owner chooses a resolution.

`services/update_product.py` opens a review flag without changing the entry's current product or disposition. It replaces an existing open flag's reason, so the new workflow must preserve earlier review context when recording an additional recommendation.

Pack services provide creation, addition, and removal operations. Detailed feasibility and tool coverage still need inspection during planning.

## Implementation choices

Implementation authorized after workshop, 2026-10-11:

- Review products and unassigned source folders as units; inspect neighboring
  products and destination lines as context. A default run selects three groups,
  with optional product-line scope and a batch limit.
- Keep physical file movement separate. The skill changes catalog relationships
  and explains pending placement; the existing `reorganize` command applies moves.
- Use the invoking LLM and new MCP services, rather than launching a separate LLM
  process. Reliable corroborating evidence supports automatic correction; plausible
  competing interpretations become recommendations.
- Store coverage, resumable runs, historical findings, and explicit owner choices
  in additive database tables. Fingerprints cover content, evidence, assignments,
  and membership, while identical metadata refreshes do not reset coverage.
- Reuse existing product and pack services inside one transaction. Preserve
  keep/superseded dispositions and unrelated open review context. Historical
  findings use stable file IDs and survive replacement of entry identities.

## Design questions addressed by the implementation

- Evidence criteria are specified in the skill: reliable identifiers, explicit release evidence, and corroborating bibliographic context; similarity alone does not establish identity. Real-world judgment quality needs usage evidence.
- Invocation resumes a bounded whole-catalog pass or a selected product line. Explicit arbitrary folder scoping is not exposed; unassigned folders are natural coverage units.
- Physical reorganization remains a separate command, as described above.
- Products and unassigned folders define coverage units; current and destination groups are checked with content/evidence/relationship fingerprints.
- Database findings retain explanations, operations, before/after context, stable file IDs, and owner resolution facts, independently of entry foreign keys.
- Deferred findings append linked blocks to existing review flags. The updated review-items skill presents group recommendations once and resolves them through a dedicated tool that preserves other questions.
- Ordered assignment/create/add/remove operations use one transaction and a savepoint; invalid corrections roll back and become review findings. Stale snapshots and unchanged owner decisions fail without advancing coverage or raising duplicate questions. No filesystem atomicity is claimed.

## Quality rubric

This rubric judges the callable library organization review skill: improving catalog relationships and the corresponding library organization, automatically correcting clear-cut issues and deferring judgment calls to `review-items`.

- **Organization quality:** Product, product-line, and pack relationships make content easier to find and understand, while preserving meaningful edition and release distinctions.
- **Evidence-based judgment:** Corrections follow reliable evidence; uncertainty is recognized and explained when deciding what to apply automatically.
- **Useful autonomy:** Clear-cut improvements happen with little supervision, keeping the owner's review effort focused on decisions that need their judgment.
- **Review usefulness:** Deferred recommendations provide enough context, evidence, and concrete options to resolve them through `review-items`.
- **Stability and preservation:** Changes preserve content and prior decisions; repeated reviews avoid unnecessary churn and duplicate recommendations.

Approved 2026-10-11. These dimensions are assessed qualitatively, without scores or fixed rating levels.
