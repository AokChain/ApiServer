"""Wallet API args"""
from webargs import fields, validate

history_args = {
    "count": fields.Int(missing=100, validate=lambda v: v > 0 and v <= 500),
    "before": fields.Str(missing=None),
    "after": fields.Str(missing=None),
    "addresses": fields.List(
        fields.Str, missing=[], validate=validate.Length(min=1, max=20)
    )
}

addresses_args = {
    "addresses": fields.List(fields.Str, missing=[], validate=validate.Length(min=1, max=500))
}

broadcast_args = {
    "raw": fields.Str(required=True)
}

utxo_args = {
    "outputs": fields.List(fields.Dict, missing=[])
}

unspent_args = {
    "amount": fields.Int(missing=0, validate=validate.Range(min=0)),
    "token": fields.Str(missing="AOK")
}

check_args = {
    "addresses": fields.List(
        fields.Str, missing=[], validate=validate.Length(min=1, max=20)
    )
}
