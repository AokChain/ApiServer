from server.services import BlockService
from server.sync import log_message
from server.utils import make_request
from pony import orm
import sys


def find_missing_tx(txid):
    log_message(f"Looking up txid={txid} on node")

    raw = make_request("getrawtransaction", [txid, True])

    if raw["error"] is not None:
        log_message(f"Node error: {raw['error']}")
        return

    result = raw["result"]
    blockhash = result.get("blockhash")

    if blockhash is None:
        log_message("Tx exists on node but is unconfirmed (mempool)")
        return

    block = make_request("getblock", [blockhash])

    if block["error"] is not None:
        log_message(f"Node error fetching block: {block['error']}")
        return

    height = block["result"]["height"]
    log_message(f"Tx is in block height={height} hash={blockhash}")

    with orm.db_session:
        db_block = BlockService.get_by_hash(blockhash)

        if db_block:
            log_message(
                f"That block IS in the DB (height={db_block.height}); "
                f"the tx was skipped during sync — re-indexing needed"
            )
        else:
            log_message(
                f"That block is NOT in the DB; "
                f"rollback target should be height {height - 1} or earlier"
            )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python find_missing_tx.py <txid>")
        raise SystemExit(1)

    find_missing_tx(sys.argv[1])
