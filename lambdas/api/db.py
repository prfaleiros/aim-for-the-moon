"""DynamoDB helpers (copied from the JDM app and trimmed; owned by this repo)."""
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key

_table = None


def _to_ddb(obj):
    if isinstance(obj, dict):
        return {k: _to_ddb(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_to_ddb(i) for i in obj]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj


def _from_ddb(obj):
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(i) for i in obj]
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def put(item: dict):
    table().put_item(Item=_to_ddb(item))


def get(pk: str, sk: str = "META"):
    item = table().get_item(Key={"PK": pk, "SK": sk}).get("Item")
    return _from_ddb(item) if item else None


def _query(**kwargs) -> list:
    items = []
    while True:
        resp = table().query(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return [_from_ddb(i) for i in items]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def query_pk(pk: str, sk_prefix: str | None = None) -> list:
    cond = Key("PK").eq(pk)
    if sk_prefix:
        cond &= Key("SK").begins_with(sk_prefix)
    return _query(KeyConditionExpression=cond)


def query_gsi1(gsi1pk: str) -> list:
    return _query(IndexName="GSI1", KeyConditionExpression=Key("GSI1PK").eq(gsi1pk))


def scan_order_parts() -> list:
    """Every part that came from an order. One filtered scan: at this volume (hundreds of items) it is
    cheaper than maintaining a second index; revisit if the table ever grows into the tens of thousands."""
    kwargs = {"FilterExpression": Attr("PK").begins_with("PART#") & Attr("order_id").exists()}
    items = []
    while True:
        resp = table().scan(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return [_from_ddb(i) for i in items]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def delete(pk: str, sk: str = "META"):
    table().delete_item(Key={"PK": pk, "SK": sk})


def response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
