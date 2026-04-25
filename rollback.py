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
from server.sync import log_message
from server.models import db
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

    block_ids = (
        f"(SELECT id FROM chain_blocks WHERE height > {target_height})"
    )
    tx_ids = (
        f"(SELECT id FROM chain_transactions WHERE block IN {block_ids})"
    )

    steps = [
        (
            "Clearing self-references in blocks to be deleted",
            "UPDATE chain_blocks SET previous_block = NULL, "
            f"next_block = NULL WHERE height > {target_height}",
        ),
        (
            "Clearing next_block on kept tip",
            "UPDATE chain_blocks SET next_block = NULL "
            f"WHERE height = {target_height}",
        ),
        (
            "Deleting inputs",
            f"DELETE FROM chain_inputs WHERE transaction IN {tx_ids}",
        ),
        (
            "Deleting outputs",
            f"DELETE FROM chain_outputs WHERE transaction IN {tx_ids}",
        ),
        (
            "Deleting transaction indexes",
            "DELETE FROM chain_transaction_index "
            f"WHERE transaction IN {tx_ids}",
        ),
        (
            "Deleting address<->transaction m2m",
            "DELETE FROM chain_address_transactions "
            f"WHERE transaction IN {tx_ids}",
        ),
        (
            "Deleting transactions",
            f"DELETE FROM chain_transactions WHERE block IN {block_ids}",
        ),
        (
            "Deleting blocks",
            f"DELETE FROM chain_blocks WHERE height > {target_height}",
        ),
        (
            "Recomputing balances from unspent outputs",
            "UPDATE chain_address_balance b SET balance = ("
            "  SELECT COALESCE(SUM(o.amount), 0) FROM chain_outputs o"
            "  WHERE o.address = b.address"
            "  AND o.currency = b.currency"
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM chain_inputs i WHERE i.vout = o.id"
            "  )"
            ")",
        ),
    ]

    overall_start = datetime.now()

    for label, sql in steps:
        log_message(label)
        start = datetime.now()
        db.execute(sql)
        elapsed = (datetime.now() - start).total_seconds()
        log_message(f"  done in {elapsed:.1f}s")

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
