from server.models import Block, db
from server.utils import make_request
from server.sync import log_message
from pony import orm
import sys


@orm.db_session
def deep_check(blockhash):
    log_message(f"Input: {blockhash!r}  len={len(blockhash)}")

    # 1. Pony lookup by blockhash
    by_hash = Block.get(blockhash=blockhash)
    log_message(f"Block.get(blockhash=...) = {by_hash}")

    # 2. Same but lowercased
    by_hash_lower = Block.get(blockhash=blockhash.lower())
    log_message(f"Block.get(blockhash=lower) = {by_hash_lower}")

    # 3. Look up by height (from node) and see what hash the DB stores
    node_resp = make_request("getblock", [blockhash])

    if node_resp["error"] is None:
        height = node_resp["result"]["height"]
        log_message(f"Node says block is at height {height}")

        db_at_height = Block.get(height=height)

        if db_at_height:
            stored = db_at_height.blockhash
            log_message(f"DB block at height {height}:")
            log_message(f"  blockhash = {stored!r}")
            log_message(f"  len       = {len(stored)}")
            log_message(f"  == input  = {stored == blockhash}")
            log_message(f"  lower ==  = {stored.lower() == blockhash.lower()}")
            log_message(f"  strip ==  = {stored.strip() == blockhash.strip()}")
        else:
            log_message(f"No DB block at height {height}")
    else:
        log_message(f"Node error: {node_resp['error']}")

    # 4. orm.select form
    selected = orm.select(
        b for b in Block if b.blockhash == blockhash
    ).first()
    log_message(f"orm.select(...).first() = {selected}")

    # 5. Raw SQL — bypasses Pony entirely
    rows = db.select(
        "SELECT id, height, blockhash FROM chain_blocks "
        "WHERE blockhash = $blockhash LIMIT 5",
        {"blockhash": blockhash},
    )
    log_message(f"Raw SQL exact match: {rows}")

    # 6. Raw SQL with LIKE — catches whitespace/invisible chars
    rows = db.select(
        "SELECT id, height, blockhash, LENGTH(blockhash) "
        "FROM chain_blocks WHERE blockhash LIKE $pattern LIMIT 5",
        {"pattern": f"%{blockhash}%"},
    )
    log_message(f"Raw SQL LIKE %hash%: {rows}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python deep_check_block.py <blockhash>")
        raise SystemExit(1)

    deep_check(sys.argv[1])
