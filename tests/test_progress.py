from unittest.mock import AsyncMock

from rpg_librarian_mcp.progress import CliProgressReporter, McpProgressReporter


async def test_cli_reporter_renders_the_specified_format(capsys):
    reporter = CliProgressReporter()

    async with reporter.track(3) as update:
        await update(1, "a.txt", 0)
        await update(2, "b.txt", 1)
        await update(3, "c.txt", 1)

    err = capsys.readouterr().err
    assert "Processing: c.txt - 1 errors - 3/3" in err


async def test_mcp_reporter_message_matches_the_shared_format():
    ctx = AsyncMock()
    reporter = McpProgressReporter(ctx)

    async with reporter.track(4) as update:
        await update(2, "b.txt", 1)

    ctx.report_progress.assert_awaited_once_with(
        2, 4, "Processing: b.txt - 1 errors - 2/4"
    )


async def test_mcp_reporter_skips_unchanged_percentage():
    ctx = AsyncMock()
    reporter = McpProgressReporter(ctx)

    async with reporter.track(1000) as update:
        await update(1, "a.txt", 0)
        await update(2, "b.txt", 0)  # still 0% -- no new call

    assert ctx.report_progress.call_count == 1
