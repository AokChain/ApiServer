import requests
import config
import math
import json


def get_logo(name):
    cache_fix = 6

    if name == "AOK":
        return f"https://api.aok.network/static/logo/aok.svg?{cache_fix}"

    elif name == "ARTL":
        return f"https://api.aok.network/static/logo/artl.svg?{cache_fix}"

    elif name == "CCA":
        return f"https://api.aok.network/static/logo/cca.svg?{cache_fix}"

    elif name == "MEC":
        return f"https://api.aok.network/static/logo/mec.svg?{cache_fix}"

    elif name == "SERG":
        return f"https://api.aok.network/static/logo/serg.svg?{cache_fix}"

    elif name == "PAPT":
        return f"https://api.aok.network/static/logo/papt.svg?{cache_fix}"

    elif name == "CCA/USDT":
        return f"https://api.aok.network/static/logo/cca_usdt.svg?{cache_fix}"

    elif name == "MEC/HOWLING2":
        return (
            f"https://api.aok.network/static/logo/mec_howling2.svg?{cache_fix}"
        )

    elif name == "PLB":
        return f"https://api.aok.network/static/logo/plb.svg?{cache_fix}"

    elif name == "NMO":
        return f"https://api.aok.network/static/logo/nmo.svg?{cache_fix}"

    elif name == "NOL":
        return f"https://api.aok.network/static/logo/nol.svg?{cache_fix}"

    elif name == "GND":
        return f"https://api.aok.network/static/logo/gnd.svg?{cache_fix}"

    elif name == "CCL":
        return f"https://api.aok.network/static/logo/ccl.svg?{cache_fix}"

    elif name == "DZTB":
        return f"https://api.aok.network/static/logo/dztb.png?{cache_fix}"

    elif name == "DHTB":
        return f"https://api.aok.network/static/logo/dhtb.png?{cache_fix}"

    elif name == "TONG":
        return f"https://api.aok.network/static/logo/tong.png?{cache_fix}"

    boring_name = name.replace("/", ":")

    return f"https://source.boringavatars.com/bauhaus/120/{boring_name}?colors=264653,2a9d8f,e9c46a,f4a261,e76f51"


def dead_response(message="Invalid Request", rid=config.rid):
    return {"error": {"code": 404, "message": message}, "id": rid}


def response(result, error=None, rid=config.rid, pagination=None):
    result = {"error": error, "id": rid, "result": result}

    if pagination:
        result["pagination"] = pagination

    return result


def make_request(method, params=[]):
    headers = {"content-type": "text/plain;"}
    data = json.dumps({"id": config.rid, "method": method, "params": params})

    try:
        return requests.post(config.endpoint, headers=headers, data=data).json()
    except Exception:
        return dead_response()


def make_batch_request(calls):
    """Send several JSON-RPC calls in a single HTTP request.

    calls: a list of (method, params) tuples. Returns a list of response
    dicts in the same order as calls (matched back by id, so the node is
    free to reorder). On transport failure every entry is a dead_response.
    """
    headers = {"content-type": "text/plain;"}
    payload = [
        {"id": index, "method": method, "params": params}
        for index, (method, params) in enumerate(calls)
    ]
    data = json.dumps(payload)

    try:
        responses = requests.post(
            config.endpoint, headers=headers, data=data
        ).json()
    except Exception:
        return [dead_response() for _ in calls]

    if not isinstance(responses, list):
        return [dead_response() for _ in calls]

    by_id = {item.get("id"): item for item in responses}
    return [by_id.get(index, dead_response()) for index in range(len(calls))]


def reward(height):
    halvings = height // 525960

    if halvings >= 10:
        return 0

    return int(satoshis(4) // (2**halvings))


def supply(height):
    premine = satoshis(2100000000)
    reward = satoshis(4)
    halvings = 525960
    halvings_count = 0
    supply = premine + reward

    while height > halvings:
        total = halvings * reward
        reward = reward / 2
        height = height - halvings
        halvings_count += 1

        supply += total

        if halvings > 10:
            reward = 0
            break

    supply = supply + height * reward

    return {
        "halvings": int(halvings_count),
        # "supply": int(supply),
        # ToDo: fix supply calculation
        "supply": satoshis(1_000_000_000),
    }


def satoshis(value):
    return int(float(value) * math.pow(10, 8))


def amount(value, decimals=8):
    return round(float(value) / math.pow(10, decimals), decimals)
