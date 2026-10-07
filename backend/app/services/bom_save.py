"""定额树保存：树叶子、需求列、缺料贴一次保存里一起过或一起停。

保存 = 用新用量重写 bom_lines，并重算所有「当前有效」备料单的快照
（备料单的 prep_lines 与缺料贴 shortages 同源，同时重写）。
保存不是出库：本流程只读 stock_qty，绝不把账面结存改小。
已存档(archived)的旧单钉死当时用量，不在重写范围内。
"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, PrepRun
from app.services.prep_run_service import build_result, dumps


class BomSaveError(ValueError):
    """校验失败：调用方必须整笔回滚，树/单/贴都停在保存前。"""


def _validate(lines: list[dict], dish_ids: set[int], ingredient_ids: set[int]) -> None:
    seen: set[tuple[int, int]] = set()
    for idx, line in enumerate(lines, start=1):
        dish_id = line.get("dish_id")
        ingredient_id = line.get("ingredient_id")
        qty = line.get("qty_per_portion")
        if not isinstance(dish_id, int) or isinstance(dish_id, bool):
            raise BomSaveError(f"第 {idx} 行菜品无效")
        if not isinstance(ingredient_id, int) or isinstance(ingredient_id, bool):
            raise BomSaveError(f"第 {idx} 行原料无效")
        if not isinstance(qty, (int, float)) or isinstance(qty, bool) or not math.isfinite(qty):
            raise BomSaveError(f"第 {idx} 行用量必须是数字")
        if qty < 0:
            raise BomSaveError(f"第 {idx} 行用量不能为负数（{qty}）")
        if dish_id not in dish_ids:
            raise BomSaveError(f"第 {idx} 行指向不存在的菜品（id={dish_id}）")
        if ingredient_id not in ingredient_ids:
            raise BomSaveError(f"第 {idx} 行指向不存在的原料（id={ingredient_id}）")
        key = (dish_id, ingredient_id)
        if key in seen:
            raise BomSaveError("同一菜品下同一原料出现重复用量行")
        seen.add(key)


def save_bom_tree(db: Session, lines: list[dict]) -> list[BomLine]:
    """在调用方事务内全量重写定额树，并重写所有当前有效备料单/缺料贴。

    任一步失败抛 BomSaveError，由调用方 rollback——不会出现树动了单没动。
    """
    dish_ids = set(db.scalars(select(Dish.id)).all())
    ingredient_ids = set(db.scalars(select(Ingredient.id)).all())
    _validate(lines, dish_ids, ingredient_ids)

    # 1) 重写树叶子（全量替换语义）
    for old in db.scalars(select(BomLine)).all():
        db.delete(old)
    db.flush()
    saved: list[BomLine] = []
    for line in lines:
        row = BomLine(dish_id=line["dish_id"], ingredient_id=line["ingredient_id"],
                      qty_per_portion=float(line["qty_per_portion"]))
        db.add(row)
        saved.append(row)
    db.flush()  # 让同事务后续重算能读到新用量

    # 2) 用新用量重写每张当前有效备料单（需求列+缺料贴一起重写）；
    #    库存只被读取，stock_qty 不做任何写操作；archived 单不碰。
    active_runs = db.scalars(select(PrepRun).where(PrepRun.status == "active")).all()
    orders = {o.id: o for o in db.scalars(select(KitchenOrder)).all()}
    for run in active_runs:
        order = orders.get(run.order_id)
        if order is None:
            raise BomSaveError(f"备料单 {run.id} 对应订单已不存在，无法重算，整笔退回")
        run.result_json = dumps(build_result(db, order))
    db.flush()
    return saved
