from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import BomLine, Dish, Ingredient
from app.services.bom_save import BomSaveError, save_bom_tree
router = APIRouter(prefix="/bom", tags=["bom"])

class BomLineIn(BaseModel):
    dish_id: int
    ingredient_id: int
    qty_per_portion: float = Field(...)

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
        children = [{"ingredient": ings[l.ingredient_id].name, "ingredient_id": l.ingredient_id,
                     "qty": l.qty_per_portion,
                     "unit": ings[l.ingredient_id].unit}
                    for l in lines if l.dish_id == d.id]
        tree.append({"dish": d.name, "code": d.code, "dish_id": d.id, "children": children})
    return tree

@router.put("")
def save_bom(payload: BomSaveIn, db: Session = Depends(get_db)):
    """保存定额用量：树叶子 + 当前有效备料单需求列 + 缺料贴同一事务整体重写。

    校验不过（负数、指向不存在的原料/菜品、重复行等）整体回滚；
    保存不做出库，库存账面结存不变；已存档旧单不动。
    """
    lines = [m.model_dump() for m in payload.lines]
    try:
        # 单一事务：服务内任一步失败都在这里 rollback，树、单、贴全部退回保存前
        save_bom_tree(db, lines)
        db.commit()
    except BomSaveError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "count": len(lines)}
