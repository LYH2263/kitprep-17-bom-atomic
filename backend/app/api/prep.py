import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import KitchenOrder, PrepRun
from app.services.prep_run_service import build_result, dumps
router = APIRouter(prefix="/prep", tags=["prep"])

@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    order = db.get(KitchenOrder, order_id)
    if not order: raise HTTPException(404, "订单不存在")
    # 新单生效：同订单此前的有效单全部存档，旧单快照钉死当时用量，不再被定额保存改写
    for old in db.scalars(select(PrepRun).where(PrepRun.order_id == order_id, PrepRun.status == "active")).all():
        old.status = "archived"
    result = build_result(db, order)
    run = PrepRun(order_id=order_id, created_at=datetime.utcnow(),
                  result_json=dumps(result), status="active")
    db.add(run); db.commit(); db.refresh(run)
    return {"id": run.id, **result}

@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    run = db.scalars(select(PrepRun).where(PrepRun.order_id == order_id, PrepRun.status == "active")
                     .order_by(PrepRun.id.desc())).first()
    if not run:
        return run_prep(order_id=order_id, db=db)
    data = json.loads(run.result_json)
    return {"id": run.id, **data}

@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest(order_id=order_id, db=db)
    return {"order_id": order_id, "shortages": data.get("shortages", []), "stats": data.get("stats", {})}
