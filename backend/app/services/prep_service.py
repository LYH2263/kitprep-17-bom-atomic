"""Shared prep-run builder: explode order lines × BOM into a new PrepRun snapshot.

PrepRuns are append-only: every save/run inserts a new snapshot and never mutates
archived ones, so historical prep lists stay pinned to the quantities of their time.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import explode_and_merge, result_to_dict


def build_prep_result(db: Session, order: KitchenOrder) -> dict:
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def create_prep_run(db: Session, order: KitchenOrder) -> PrepRun:
    """Insert a new PrepRun snapshot for the order. Caller commits."""
    result = build_prep_result(db, order)
    run = PrepRun(order_id=order.id, created_at=datetime.utcnow(),
                  result_json=json.dumps(result, ensure_ascii=False))
    db.add(run)
    db.flush()
    return run
