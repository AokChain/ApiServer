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


def find_fork_point():
    """Walk down from the DB tip until DB hash matches node hash."""
    log_message("Searching for fork point (DB vs node)")

    with orm.db_session:
        tip = BlockService.latest_block()
        height = tip.height

    while height > 0:
        with orm.db_session:
            db_block = BlockService.get_by_height(height)
            db_hash = db_block.blockhash if db_block else None

        node_resp = make_request("getblockhash", [height])

        if node_resp["error"] is not None:
            log_message(f"Node error at height {height}: {node_resp['error']}")
            return

        node_hash = node_resp["result"]

        if db_hash == node_hash:
            log_message(
                f"Fork point: chains agree at height {height} ({node_hash})"
            )
            log_message(
                f"Roll back to height {height} to resync from divergence"
            )
            return

        # Step in chunks to avoid scanning every block at first
        step = 1 if height < 100 else 100
        height -= step


if __name__ == "__main__":
    if len(sys.argv) == 2:
        diagnose(int(sys.argv[1]))
    else:
        find_fork_point()
