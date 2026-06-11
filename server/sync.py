from .methods.transaction import Transaction
from .services import TransactionService
from .services import BalanceService
from .methods.general import General
from .services import AddressService
from .services import OutputService
from .services import InputService
from .services import BlockService
from .methods.block import Block
from datetime import datetime
from pony import orm
from . import utils
import requests

from .models import TransactionIndex
from .models import IPFSCache

from .utils import make_request
from .models import Token
from .models import db

# `Block` above is the RPC-method class; this is the Pony entity, aliased
# to avoid the name clash when querying the DB directly.
from .models import Block as BlockModel


REORG_DEPTH = 500


def log_block(message, block, tx=[]):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time = block.created.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"{now} {message}: hash={block.blockhash} height={block.height} tx={len(tx)} date='{time}'"
    )


def log_message(message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now} {message}")


def token_category(name):
    if "#" in name:
        return "unique"
    if "/" in name:
        return "sub"
    if name[0] == "@":
        return "username"
    if name[0] == "!":
        return "owner"
    return "root"


def get_ipfs_data(ipfs):
    ALLOWED_MIME = ["application/json"]
    TIMEOUT = 30

    try:
        endpoint = f"https://ipfs.aok.network/ipfs/{ipfs}"
        content = None
        parsed = False
        mime = None

        head = requests.head(endpoint, timeout=TIMEOUT)

        if head.status_code == 200:
            parsed = True

            if head.headers["Content-Type"] in ALLOWED_MIME:
                r = requests.get(endpoint, timeout=TIMEOUT)

                mime = head.headers["Content-Type"]
                content = r.text

        return parsed, content, mime

    except requests.exceptions.ReadTimeout:
        return False, None, None


@orm.db_session
def sync_ipfs_cache():
    log_message("Updating ipfs cache")

    tokens = Token.select(lambda t: t.ipfs is not None)

    for token in tokens:
        if not IPFSCache.get(ipfs=token.ipfs):
            IPFSCache(**{"ipfs": token.ipfs})

    orm.commit()

    cache = IPFSCache.select(lambda c: not c.parsed).order_by(
        IPFSCache.attempts
    )

    for entry in cache:
        log_message(f"Parsing IPFS data for {entry.ipfs}")

        parsed, content, mime = get_ipfs_data(entry.ipfs)

        log_message(f"Parsed: {str(parsed)}")

        entry.content = content
        entry.parsed = parsed
        entry.mime = mime

        if not entry.parsed:
            entry.attempts += 1

        orm.commit()


@orm.db_session
def sync_tokens():
    log_message("Updating tokens list")

    tokens = make_request("listtokens", ["", True])

    if not tokens["error"]:
        for name in tokens["result"]:
            data = tokens["result"][name]
            token = Token.get(name=name)
            ipfs = data["ipfs_hash"] if data["has_ipfs"] == 1 else None

            if not token:
                log_message(f"Added {name} to db")
                token = Token(
                    **{
                        "amount": data["amount"],
                        "reissuable": data["reissuable"],
                        "category": token_category(name),
                        "height": data["block_height"],
                        "block": data["blockhash"],
                        "units": data["units"],
                        "name": name,
                        "ipfs": ipfs,
                    }
                )

            else:
                if token.amount != data["amount"]:
                    log_message(f"Updated amount for {name}")
                    token.amount = data["amount"]

                if token.units != data["units"]:
                    log_message(f"Updated units for {name}")
                    token.units = data["units"]

                if token.reissuable != data["reissuable"]:
                    log_message(f"Updated reissuable for {name}")
                    token.reissuable = data["reissuable"]

                # ToDo: Update IPFS (?)


def process_transaction(tx_data, block, index):
    """Persist a transaction and its inputs/outputs into the DB.

    If a vin references a parent tx that is not in the DB, recursively
    fetch it from the node via load_missing_transaction.
    """
    txid = tx_data["txid"]

    existing = TransactionService.get_by_txid(txid)
    if existing:
        return existing

    created = datetime.fromtimestamp(tx_data["time"])
    coinbase = block.stake is False and index == 0
    coinstake = block.stake and index == 1
    indexes = {}

    transaction = TransactionService.create(
        utils.amount(tx_data["amount"]),
        tx_data["txid"],
        created,
        tx_data["locktime"],
        tx_data["size"],
        block,
        coinbase,
        coinstake,
    )

    for vin in tx_data["vin"]:
        if "coinbase" in vin:
            continue

        prev_tx = TransactionService.get_by_txid(vin["txid"])

        if prev_tx is None:
            log_message(
                f"MISSING prev tx: txid={vin['txid']} "
                f"vout={vin['vout']} consumed by {tx_data['txid']} "
                f"at height {block.height}; loading from node"
            )
            prev_tx = load_missing_transaction(vin["txid"])

        prev_out = OutputService.get_by_prev(prev_tx, vin["vout"])

        prev_out.address.transactions.add(transaction)
        balance = BalanceService.get_by_currency(
            prev_out.address, prev_out.currency
        )
        balance.balance -= prev_out.amount

        InputService.create(
            vin["sequence"], vin["vout"], transaction, prev_out
        )

    for vout in tx_data["vout"]:
        if vout["scriptPubKey"]["type"] in ["nonstandard", "nulldata"]:
            continue

        amount = utils.amount(vout["valueSat"])
        currency = "AOK"
        timelock = 0

        if "token" in vout["scriptPubKey"]:
            timelock = vout["scriptPubKey"]["token"]["token_lock_time"]
            currency = vout["scriptPubKey"]["token"]["name"]
            amount = vout["scriptPubKey"]["token"]["amount"]

        if "timelock" in vout["scriptPubKey"]:
            timelock = vout["scriptPubKey"]["timelock"]

        script = vout["scriptPubKey"]["addresses"][0]
        address = AddressService.get_by_address(script)

        if not address:
            address = AddressService.create(script)

        address.transactions.add(transaction)

        output = OutputService.create(
            transaction,
            amount,
            vout["scriptPubKey"]["type"],
            address,
            vout["scriptPubKey"]["hex"],
            vout["n"],
            currency,
            timelock,
        )

        balance = BalanceService.get_by_currency(address, currency)

        if not balance:
            balance = BalanceService.create(address, currency)

        balance.balance += output.amount

        if output.currency not in indexes:
            indexes[output.currency] = 0

        indexes[output.currency] += output.amount

    for currency in indexes:
        if TransactionIndex.get(
            currency=currency, transaction=transaction
        ):
            continue

        TransactionIndex(
            **{
                "created": transaction.created,
                "amount": indexes[currency],
                "transaction": transaction,
                "currency": currency,
            }
        )

    return transaction


def load_missing_transaction(txid):
    """Fetch a missing transaction from the node and persist it.

    The transaction's containing block must already be in the DB. If a
    parent tx is also missing, this recurses.
    """
    response = Transaction.info(txid, False)

    if response["error"] is not None:
        raise RuntimeError(
            f"Node error fetching tx {txid}: {response['error']}"
        )

    tx_data = response["result"]
    blockhash = tx_data.get("blockhash")

    if not blockhash:
        raise RuntimeError(
            f"Missing tx {txid} is not confirmed on node"
        )

    block = BlockService.get_by_hash(blockhash)

    if block is None:
        block_data = make_request("getblock", [blockhash])["result"]
        raise RuntimeError(
            f"Cannot recover tx {txid}: containing block {blockhash} "
            f"(height {block_data['height']}) is not in the DB. "
            f"Roll back to height {block_data['height'] - 1} or earlier."
        )

    block_data = make_request("getblock", [blockhash])["result"]
    tx_index = block_data["tx"].index(txid)

    if block.stake and tx_index == 0:
        raise RuntimeError(
            f"Tx {txid} is the coinstake placeholder of block "
            f"{blockhash}; not loadable"
        )

    log_message(
        f"Loading missing tx {txid} into block height={block.height}"
    )

    return process_transaction(tx_data, block, tx_index)


def rollback_to_height(target_height):
    """Bulk-delete every block above target_height and recompute balances.

    Bypasses Pony's per-row before_delete hooks (which would update each
    balance incrementally) in favor of a single balance recomputation
    pass at the end -- orders of magnitude faster for large rollbacks.

    The caller owns the surrounding db_session and the commit.
    """
    block_ids = (
        f"(SELECT id FROM chain_blocks WHERE height > {target_height})"
    )
    tx_ids = (
        f"(SELECT id FROM chain_transactions WHERE block IN {block_ids})"
    )

    steps = [
        (
            "Clearing self-references in blocks to be deleted",
            "UPDATE chain_blocks SET previous_block = NULL "
            f"WHERE height > {target_height}",
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

    for label, sql in steps:
        log_message(label)
        start = datetime.now()
        db.execute(sql)
        elapsed = (datetime.now() - start).total_seconds()
        log_message(f"  done in {elapsed:.1f}s")


def find_reorg_height(tip_height, node_height):
    """Lowest height in the last REORG_DEPTH blocks whose stored hash
    disagrees with the node, or None if the DB matches the node.

    Only heights the node actually has (<= node_height) are compared, and
    the whole window is fetched in one batched RPC. If the node fails to
    answer for any height in the window the scan is abandoned (returns
    None) -- so a node that is merely behind or briefly unreachable can
    never trigger a rollback.
    """
    ceiling = min(tip_height, node_height)

    if ceiling < 1:
        return None

    floor = max(1, ceiling - REORG_DEPTH + 1)

    node_hashes = Block.blockhashes(floor, ceiling)

    if len(node_hashes) != ceiling - floor + 1:
        log_message(
            "Skipping reorg check: node did not return all hashes for "
            f"{floor}..{ceiling}"
        )
        return None

    db_hashes = dict(
        orm.select(
            (b.height, b.blockhash)
            for b in BlockModel
            if b.height >= floor and b.height <= ceiling
        )
    )

    for height in range(floor, ceiling + 1):
        if db_hashes.get(height) != node_hashes[height]:
            if height == floor and floor > 1:
                log_message(
                    "Reorg reaches the bottom of the scan window; it may "
                    f"be deeper than {REORG_DEPTH} blocks and will keep "
                    "unwinding on subsequent cycles"
                )

            return height

    return None


@orm.db_session
def sync_blocks():
    if not BlockService.latest_block():
        data = Block.height(0)["result"]
        created = datetime.fromtimestamp(data["time"])
        signature = data["signature"] if "signature" in data else None

        block = BlockService.create(
            utils.amount(data["reward"]),
            data["hash"],
            data["height"],
            created,
            data["difficulty"],
            data["merkleroot"],
            data["chainwork"],
            data["version"],
            data["weight"],
            data["stake"],
            data["nonce"],
            data["size"],
            data["bits"],
            signature,
        )

        log_block("Genesis block", block)

        orm.commit()

    current_height = General.current_height()
    latest_block = BlockService.latest_block()

    log_message(
        f"Current node height: {current_height}, db height: {latest_block.height}"
    )

    reorg_height = find_reorg_height(latest_block.height, current_height)

    if reorg_height is not None:
        target = reorg_height - 1

        log_message(
            f"Found reorg at height {reorg_height} "
            f"(db tip {latest_block.height}); rolling back to {target} "
            f"({latest_block.height - target} blocks)"
        )

        rollback_to_height(target)
        orm.commit()

        # Resume forward sync on the next cycle with a fresh session so we
        # never read Pony-cached objects invalidated by the bulk delete.
        return

    # Quick hack to prevent memory overload
    next_height = current_height + 1
    if next_height > latest_block.height + 10000:
        next_height = latest_block.height + 10000

    for height in range(latest_block.height + 1, next_height):
        block_data = Block.height(height)["result"]
        created = datetime.fromtimestamp(block_data["time"])
        signature = (
            block_data["signature"] if "signature" in block_data else None
        )

        block = BlockService.create(
            utils.amount(block_data["reward"]),
            block_data["hash"],
            block_data["height"],
            created,
            block_data["difficulty"],
            block_data["merkleroot"],
            block_data["chainwork"],
            block_data["version"],
            block_data["weight"],
            block_data["stake"],
            block_data["nonce"],
            block_data["size"],
            block_data["bits"],
            signature,
        )

        block.previous_block = latest_block

        log_block("New block", block, block_data["tx"])

        for index, txid in enumerate(block_data["tx"]):
            if block.stake and index == 0:
                continue

            tx_data = Transaction.info(txid, False)["result"]
            process_transaction(tx_data, block, index)

        latest_block = block
        orm.commit()
