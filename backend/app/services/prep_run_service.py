"""备料单重算：读取订单行/定额/库存，展开合并为备料单+缺料贴快照。

注意：本模块只读库存，绝不在此处或定额保存时改动 stock_qty（保存不是出库）。
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine
from app.services.bom_engine import explode_and_merge, result_to_dict


def build_result(db: Session, order: KitchenOrder) -> dict:
    """按当前定额树重算某订单的备料单与缺料贴。"""
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def dumps(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
