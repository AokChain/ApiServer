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

def log_block(message, block, tx=[]):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time = block.created.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now} {message}: hash={block.blockhash} height={block.height} tx={len(tx)} date='{time}'")

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

    tokens = Token.select(
        lambda t: t.ipfs is not None
    )

    for token in tokens:
        if not IPFSCache.get(ipfs=token.ipfs):
            IPFSCache(**{
                "ipfs": token.ipfs
            })

    orm.commit()

    cache = IPFSCache.select(
        lambda c: not c.parsed
    ).order_by(IPFSCache.attempts)

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
                token = Token(**{
                    "amount": data["amount"],
                    "reissuable": data["reissuable"],
                    "category": token_category(name),
                    "height": data["block_height"],
                    "block": data["blockhash"],
                    "units": data["units"],
                    "name": name,
                    "ipfs": ipfs
                })

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

@orm.db_session
def sync_blocks():
    if not BlockService.latest_block():
        data = Block.height(0)["result"]
        created = datetime.fromtimestamp(data["time"])
        signature = data["signature"] if "signature" in data else None

        block = BlockService.create(
            utils.amount(data["reward"]), data["hash"], data["height"], created,
            data["difficulty"], data["merkleroot"], data["chainwork"],
            data["version"], data["weight"], data["stake"], data["nonce"],
            data["size"], data["bits"], signature
        )

        log_block("Genesis block", block)

        orm.commit()

    current_height = General.current_height()
    latest_block = BlockService.latest_block()

    log_message(f"Current node height: {current_height}, db height: {latest_block.height}")

    while latest_block.blockhash != Block.blockhash(latest_block.height):
        log_block("Found reorg", latest_block)

        reorg_block = latest_block
        latest_block = reorg_block.previous_block

        reorg_block.delete()
        orm.commit()

    for height in range(latest_block.height + 1, current_height + 1):
        block_data = Block.height(height)["result"]
        created = datetime.fromtimestamp(block_data["time"])
        signature = block_data["signature"] if "signature" in block_data else None

        block = BlockService.create(
            utils.amount(block_data["reward"]), block_data["hash"], block_data["height"], created,
            block_data["difficulty"], block_data["merkleroot"], block_data["chainwork"],
            block_data["version"], block_data["weight"], block_data["stake"], block_data["nonce"],
            block_data["size"], block_data["bits"], signature
        )

        block.previous_block = latest_block

        log_block("New block", block, block_data["tx"])

        for index, txid in enumerate(block_data["tx"]):
            if block.stake and index == 0:
                continue

            tx_data = Transaction.info(txid, False)["result"]
            created = datetime.fromtimestamp(tx_data["time"])
            coinbase = block.stake is False and index == 0
            coinstake = block.stake and index == 1
            indexes = {}

            if not (transaction := TransactionService.get_by_txid(txid=tx_data["txid"])):
                transaction = TransactionService.create(
                    utils.amount(tx_data["amount"]), tx_data["txid"],
                    created, tx_data["locktime"], tx_data["size"], block,
                    coinbase, coinstake
                )

            transaction.block = block

            for vin in tx_data["vin"]:
                if "coinbase" in vin:
                    continue

                prev_tx = TransactionService.get_by_txid(vin["txid"])
                prev_out = OutputService.get_by_prev(prev_tx, vin["vout"])

                prev_out.address.transactions.add(transaction)
                balance = BalanceService.get_by_currency(prev_out.address, prev_out.currency)
                balance.balance -= prev_out.amount

                if InputService.get_by_transaction(transaction=transaction):
                    continue

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
                    transaction, amount, vout["scriptPubKey"]["type"],
                    address, vout["scriptPubKey"]["hex"],
                    vout["n"], currency,
                    timelock
                )

                balance = BalanceService.get_by_currency(address, currency)

                if not balance:
                    balance = BalanceService.create(address, currency)

                balance.balance += output.amount

                if output.currency not in indexes:
                    indexes[output.currency] = 0

                indexes[output.currency] += output.amount

            for currency in indexes:
                if TransactionIndex.get(currency=currency, transaction=transaction):
                    continue

                TransactionIndex(**{
                    "created": transaction.created,
                    "amount": indexes[currency],
                    "transaction": transaction,
                    "currency": currency,
                })

        latest_block = block
        orm.commit()

@orm.db_session
def sync_mempool():
    mempool = General.mempool()['result']

    for tx in mempool['tx']:
        tx_data = Transaction.info(tx, False)['result']
        created = datetime.fromtimestamp(tx_data['timestamp'])
        if not (transaction := TransactionService.get_by_txid(tx_data['txid'])):
            print(f"adding mempool tx {tx} to db")
            transaction = TransactionService.create(
                utils.amount(tx_data['amount']), tx_data['txid'],
                created, tx_data['locktime'], tx_data['size']
            )

        for vin in tx_data["vin"]:
            if "coinbase" in vin:
                continue

            prev_tx = TransactionService.get_by_txid(vin["txid"])
            prev_out = OutputService.get_by_prev(prev_tx, vin["vout"])

            prev_out.address.transactions.add(transaction)
            balance = BalanceService.get_by_currency(prev_out.address, prev_out.currency)
            balance.balance -= prev_out.amount

            if InputService.get_by_transaction(transaction=transaction):
                continue

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

            OutputService.create(
                transaction, amount, vout["scriptPubKey"]["type"],
                address, vout["scriptPubKey"]["hex"],
                vout["n"], currency,
                timelock
            )

    pass
