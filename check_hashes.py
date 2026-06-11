"""
Audit chain block hashes against the node.

Read-only: walks every block in the DB (in batches of 500) and reports
any height whose stored hash disagrees with the node's getblockhash for
that height. Nothing is ever modified or deleted -- it only prints the
problematic heights and hashes.

Usage:
    python check_hashes.py                  # whole DB
    python check_hashes.py 2700000          # from height 2700000 to tip
    python check_hashes.py 2700000 2750000  # explicit range
"""

from server.methods.block import Block as BlockMethod
from server.methods.general import General
from server.services import BlockService
from server.sync import log_message
from server.models import Block
from pony import orm
import sys


BATCH = 500


@orm.db_session
def check(start=None, end=None):
    latest = BlockService.latest_block()

    if not latest:
        log_message("No blocks in database")
        return

    node_height = General.current_height()

    if node_height <= 0:
        log_message("Node unreachable (current height 0); aborting")
        return

    db_min = orm.min(b.height for b in Block)
    db_max = latest.height

    scan_start = db_min if start is None else max(start, db_min)
    scan_end = db_max if end is None else min(end, db_max)

    # Never compare heights the node has not reached yet: a node that is
    # behind would otherwise look like a wall of discrepancies.
    if scan_end > node_height:
        log_message(
            f"DB tip {scan_end} is above node tip {node_height}; heights "
            f"{node_height + 1}..{scan_end} are skipped (node has not "
            "reached them)"
        )
        scan_end = node_height

    if scan_start > scan_end:
        log_message("Nothing to scan")
        return

    log_message(
        f"Auditing heights {scan_start}..{scan_end} "
        f"({scan_end - scan_start + 1} blocks) in batches of {BATCH}"
    )

    mismatches = 0
    missing_db = 0
    missing_node = 0
    checked = 0
    batches = 0

    batch_start = scan_start

    while batch_start <= scan_end:
        batch_end = min(batch_start + BATCH - 1, scan_end)

        db_hashes = dict(
            orm.select(
                (b.height, b.blockhash)
                for b in Block
                if b.height >= batch_start and b.height <= batch_end
            )
        )
        node_hashes = BlockMethod.blockhashes(batch_start, batch_end)

        for height in range(batch_start, batch_end + 1):
            db_hash = db_hashes.get(height)
            node_hash = node_hashes.get(height)
            checked += 1

            if db_hash is None:
                missing_db += 1
                log_message(
                    f"MISSING-IN-DB height={height} node={node_hash}"
                )

            elif node_hash is None:
                missing_node += 1
                log_message(
                    f"NO-NODE-HASH  height={height} db={db_hash} "
                    "(node returned nothing)"
                )

            elif db_hash != node_hash:
                mismatches += 1
                log_message(
                    f"MISMATCH      height={height} db={db_hash} "
                    f"node={node_hash}"
                )

        batches += 1

        # Sparse heartbeat so a multi-million-block scan shows progress
        # without burying the actual findings.
        if batches % 100 == 0:
            log_message(
                f"...checked up to {batch_end} "
                f"({mismatches} mismatches so far)"
            )

        batch_start = batch_end + 1

    log_message(
        f"Done. checked={checked} mismatches={mismatches} "
        f"missing_in_db={missing_db} no_node_hash={missing_node}"
    )

    if mismatches == 0 and missing_db == 0 and missing_node == 0:
        log_message(
            "DB is consistent with the node across the scanned range"
        )


if __name__ == "__main__":
    start_arg = None
    end_arg = None

    if len(sys.argv) >= 2:
        start_arg = int(sys.argv[1])

    if len(sys.argv) >= 3:
        end_arg = int(sys.argv[2])

    check(start_arg, end_arg)
