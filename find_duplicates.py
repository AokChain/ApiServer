from server.models import Output
from server.sync import log_message
from pony import orm


@orm.db_session
def find_duplicates():
    log_message("Searching for duplicate outputs (same txid + n)")

    groups = orm.select(
        (o.transaction.txid, o.n, orm.count(o))
        for o in Output
    )

    duplicates = [
        (txid, n, count) for txid, n, count in groups if count > 1
    ]

    if not duplicates:
        log_message("No duplicates found")
        return

    log_message(f"Found {len(duplicates)} duplicate (txid, n) groups")

    for txid, n, count in duplicates:
        log_message(f"  txid={txid} n={n} count={count}")

        outputs = orm.select(
            o for o in Output
            if o.transaction.txid == txid and o.n == n
        )

        for output in outputs:
            spent = output.vin is not None
            log_message(
                f"    id={output.id} tx_id={output.transaction.id} "
                f"block_height={output.transaction.block.height} "
                f"amount={output.amount} currency={output.currency} "
                f"address={output.address.address} spent={spent}"
            )


if __name__ == "__main__":
    find_duplicates()
