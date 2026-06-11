"""
Fast chain rollback using bulk SQL.

Bypasses Pony's per-row before_delete hooks (which would update each
balance incrementally) in favor of a single balance recomputation pass
at the end. Orders of magnitude faster than the row-by-row approach for
large rollbacks.

Usage:
    python rollback.py            # uses TARGET_HEIGHT below
    python rollback.py 2778450    # explicit target
"""

from server.services import BlockService
from server.sync import rollback_to_height
from server.sync import log_message
from datetime import datetime
from pony import orm
import sys


TARGET_HEIGHT = 2778450


@orm.db_session
def rollback(target_height):
    if not isinstance(target_height, int):
        raise TypeError("target_height must be int")

    latest = BlockService.latest_block()

    if not latest:
        log_message("No blocks in database")
        return

    if latest.height <= target_height:
        log_message(
            f"Database height ({latest.height}) already at or below "
            f"target ({target_height}); nothing to do"
        )
        return

    log_message(
        f"Fast rollback: {latest.height} -> {target_height} "
        f"({latest.height - target_height} blocks)"
    )

    overall_start = datetime.now()

    rollback_to_height(target_height)
    orm.commit()

    total = (datetime.now() - overall_start).total_seconds()
    new_latest = BlockService.latest_block()
    log_message(
        f"Rollback complete in {total:.1f}s; latest height: "
        f"{new_latest.height if new_latest else 'none'}"
    )


if __name__ == "__main__":
    target = TARGET_HEIGHT

    if len(sys.argv) == 2:
        target = int(sys.argv[1])

    rollback(target)
