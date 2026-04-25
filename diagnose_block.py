from server.services import BlockService
from server.utils import make_request
from server.sync import log_message
from pony import orm
import sys


@orm.db_session
def diagnose(height):
    db_block = BlockService.get_by_height(height)

    if db_block is None:
        log_message(f"No block at height {height} in DB")
        return

    log_message(f"DB hash   at height {height}: {db_block.blockhash}")

    node_resp = make_request("getblockhash", [height])

    if node_resp["error"] is not None:
        log_message(f"Node error: {node_resp['error']}")
        return

    node_hash = node_resp["result"]
    log_message(f"Node hash at height {height}: {node_hash}")

    if db_block.blockhash == node_hash:
        log_message("Hashes match")
    else:
        log_message("MISMATCH — DB has a stale chain at this height")


def heights_agree(height):
    with orm.db_session:
        db_block = BlockService.get_by_height(height)
        db_hash = db_block.blockhash if db_block else None

    node_resp = make_request("getblockhash", [height])

    if node_resp["error"] is not None:
        return None

    return db_hash == node_resp["result"]


def find_fork_point(known_disagree=None):
    """Binary search for the highest height where DB and node still agree.

    Below the fork point: chains share history (same hashes).
    Above the fork point: DB has a stale fork (different hashes).
    """
    log_message("Searching for fork point")

    with orm.db_session:
        tip = BlockService.latest_block()
        tip_height = tip.height

    high = known_disagree

    if high is None:
        for offset in [1, 10, 100, 1000, 10000, 100000, 1000000]:
            h = max(0, tip_height - offset)
            agree = heights_agree(h)
            if agree is False:
                high = h
                break
        if high is None:
            log_message("No disagreement found in samples; chain consistent")
            return

    log_message(f"Confirmed disagreement at height {high}")

    low = 0
    if heights_agree(low) is not True:
        log_message("Genesis disagrees — manual investigation required")
        return

    # Invariant: heights_agree(low) is True, heights_agree(high) is False
    while high - low > 1:
        mid = (low + high) // 2
        agree = heights_agree(mid)

        if agree is True:
            low = mid
        else:
            high = mid

        log_message(f"  low={low} high={high}")

    log_message(f"Fork point: highest agreeing height = {low}")
    log_message(f"Lowest disagreeing height = {high}")
    log_message(f"Set TARGET_HEIGHT = {low} in rollback.py and resync")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        find_fork_point()
    elif len(sys.argv) == 2:
        diagnose(int(sys.argv[1]))
    elif len(sys.argv) == 3 and sys.argv[1] == "fork":
        find_fork_point(known_disagree=int(sys.argv[2]))
    else:
        print("Usage:")
        print("  python diagnose_block.py            # auto-find fork")
        print("  python diagnose_block.py <height>   # check single height")
        print("  python diagnose_block.py fork <h>   # binary search using a known-disagreeing height")
        raise SystemExit(1)
