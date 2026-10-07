from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder
from app.services.prep_service import create_prep_run
router = APIRouter(prefix="/bom", tags=["bom"])

class BomLineIn(BaseModel):
    dish_id: int
    ingredient_id: int
    qty_per_portion: float = Field(allow_inf_nan=False)

class BomSaveIn(BaseModel):
    lines: list[BomLineIn]

@router.get("")
def list_bom(db: Session = Depends(get_db)):
    dishes = {d.id: d for d in db.scalars(select(Dish)).all()}
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    rows = db.scalars(select(BomLine).order_by(BomLine.dish_id, BomLine.id)).all()
    return [{"id": r.id, "dish_id": r.dish_id, "dish_name": dishes[r.dish_id].name,
             "ingredient_id": r.ingredient_id, "ingredient_name": ings[r.ingredient_id].name,
             "qty_per_portion": r.qty_per_portion, "unit": ings[r.ingredient_id].unit} for r in rows]

@router.get("/tree")
def bom_tree(db: Session = Depends(get_db)):
    dishes = db.scalars(select(Dish).order_by(Dish.id)).all()
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    lines = db.scalars(select(BomLine)).all()
    tree = []
    for d in dishes:
        children = [{"line_id": l.id, "ingredient_id": l.ingredient_id,
                     "ingredient": ings[l.ingredient_id].name, "qty": l.qty_per_portion,
                     "unit": ings[l.ingredient_id].unit}
                    for l in lines if l.dish_id == d.id]
        tree.append({"dish_id": d.id, "dish": d.name, "code": d.code, "children": children})
    return tree

@router.put("")
def save_bom(payload: BomSaveIn, db: Session = Depends(get_db)):
    """Save BOM quantities atomically: validate every line first, then in one
    transaction rewrite the tree AND regenerate the effective prep runs (open
    orders) so prep list and shortage notes follow the new quantities.
    Never touches ingredient stock (this is not a stock-out), never mutates
    archived PrepRuns. Any failure rolls tree, list and notes back together."""
    dishes = {d.id: d for d in db.scalars(select(Dish)).all()}
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    errors: list[str] = []
    seen: set[tuple[int, int]] = set()
    for i, l in enumerate(payload.lines, start=1):
        if l.qty_per_portion < 0:
            errors.append(f"第{i}行用量为负数（{l.qty_per_portion}），用量不能小于 0")
        if l.dish_id not in dishes:
            errors.append(f"第{i}行指向不存在的菜品 #{l.dish_id}")
        if l.ingredient_id not in ings:
            errors.append(f"第{i}行指向不存在的原料 #{l.ingredient_id}")
        key = (l.dish_id, l.ingredient_id)
        if key in seen:
            errors.append(f"第{i}行与前面重复（菜品 #{l.dish_id} × 原料 #{l.ingredient_id}）")
        seen.add(key)
    if errors:
        # 一行也不过：树、备料单、缺料贴全部保持保存前
        raise HTTPException(status_code=422, detail=errors)
    try:
        db.execute(delete(BomLine))
        for l in payload.lines:
            db.add(BomLine(dish_id=l.dish_id, ingredient_id=l.ingredient_id,
                           qty_per_portion=l.qty_per_portion))
        db.flush()
        # 当前有效备料单（open 订单）与缺料贴在同一事务里按新用量重写；
        # 旧 run 只新增不修改，存档钉死当时用量
        open_orders = db.scalars(
            select(KitchenOrder).where(KitchenOrder.status == "open").order_by(KitchenOrder.id)
        ).all()
        runs = [create_prep_run(db, o) for o in open_orders]
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "ok": True,
        "line_count": len(payload.lines),
        "rewritten_runs": [{"run_id": r.id, "order_id": r.order_id} for r in runs],
        "tree": bom_tree(db),
    }
