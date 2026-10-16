"""MCP interface for durable organization reviews."""

from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

from ..services import organization_review as review
from .tools import _read, _write


def register(mcp: FastMCP, catalog: Path) -> None:
    @mcp.tool
    def organization_review_start(
        line_id: int | None = None, max_groups: int = 3
    ) -> dict[str, Any]:
        """Start or resume a database-backed review of catalog organization.

        Select up to max_groups (1..20) products/unassigned folders not examined
        at their current fingerprint, never-examined first. An unfinished run for
        this scope is resumed, not replaced. With line_id, review only that line.
        No catalog assignments change. Returns run_id, remaining_groups, resume_at.
        """
        return _write(catalog, review.start, line_id=line_id, max_groups=max_groups)

    @mcp.tool
    def organization_review_group(
        group_key: str, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        """Inspect a product:<id>, line:<id>, or folder:<root>:<path> group.

        Returns its fingerprint, paginated files and their effective entries,
        product coordinates, hints, and prior findings/owner decisions for the
        page. Unlike other item tools this explicitly returns stable file_ids:
        use them for atomic pack changes and recommendations. Use report_entry
        for full evidence. Inspect neighboring products/lines before deciding.
        next_offset indicates another page. Fingerprints protect against stale
        corrections; include every touched group and destination in expected.
        """
        return _read(
            catalog, review.inspect, group_key=group_key, offset=offset, limit=limit
        )

    @mcp.tool
    def organization_review_commit(
        run_id: int,
        group_key: str,
        expected: dict[str, str],
        summary: str,
        operations: list[review.Operation] | None = None,
        current: str | None = None,
        proposed: str | None = None,
        evidence: str | None = None,
        recommendations: list[review.Recommendation] | None = None,
        new_evidence: str | None = None,
    ) -> dict[str, Any]:
        """Record one examined group and atomically apply its clear-cut correction.

        expected maps group_key to the current fingerprint for source, related
        groups and destination. Operations are ordered assign_product,
        create_pack, add_to_pack, remove_from_pack. A key on a create/remove
        operation names its generated entry_ids in later operations (strings).
        Product assignment preserves keep/superseded. Pack membership takes
        explicit file_ids; create_pack selects a whole root/folder. Detached
        filed members must be reassigned in the same transaction.

        Applied corrections need current/proposed/evidence explanations. On
        validation failure all correction effects roll back and one complete
        recommendation is stored for review; stale snapshots instead fail with
        no coverage advancement. Recommendations need file_ids and the same
        explanations, with optional proposed operations. Owner decisions with
        unchanged evidence cannot be automatically revisited. new_evidence must
        explain materially changed evidence when reconsidering a resolved choice.
        With no operations/recommendations, records examined-with-no-findings.
        Returns a receipt; files are never moved or deleted.
        """
        return _write(
            catalog,
            review.commit,
            run_id=run_id,
            group_key=group_key,
            expected=expected,
            summary=summary,
            operations=operations,
            current=current,
            proposed=proposed,
            evidence=evidence,
            recommendations=recommendations,
            new_evidence=new_evidence,
        )

    @mcp.tool
    def organization_review_receipt(run_id: int) -> dict[str, Any]:
        """What this run examined, changed, deferred, and where it resumes.

        Applied/deferred finding IDs point to explanations in the catalog's
        organization_finding table and organization_review_findings.
        """
        return _read(catalog, review.receipt, run_id=run_id)

    @mcp.tool
    def organization_review_findings(
        status: Literal["deferred", "applied", "resolved", "all"] = "deferred",
        after_id: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Organization recommendations and change records, with stable finding IDs.

        Includes current entry IDs derived from stable file IDs, the recorded
        before/after context, evidence, operations, and owner resolution. Findings
        survive deletion of an entry when files become pack members. Paginate with
        next_after_id until truncated is false. This is part of review-items.
        """
        return _read(
            catalog, review.findings, status=status, after_id=after_id, limit=limit
        )

    @mcp.tool
    def organization_review_resolve(
        finding_id: int,
        decision: Literal["apply", "reject", "alternative"],
        note: str,
        expected: dict[str, str] | None = None,
        operations: list[review.Operation] | None = None,
    ) -> dict[str, Any]:
        """Save an owner's explicitly chosen resolution to a deferred finding.

        apply executes its stored proposal; alternative uses the supplied
        operations; reject keeps current organization. Applying needs fresh group
        fingerprints in expected, including the destination. The entire change and
        owner decision commit together. note explains the owner's choice. Only this
        finding's review flag text is removed; unrelated review context remains.
        No physical moves. Do not call without the user's chosen resolution.
        """
        return _write(
            catalog,
            review.resolve,
            finding_id=finding_id,
            decision=decision,
            note=note,
            expected=expected,
            operations=operations,
        )
