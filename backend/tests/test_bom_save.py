"""BOM 用量保存：树 / 备料单 / 缺料贴一次保存里一起过或一起停。

- 保存成功：bom_lines 重写、open 订单追加新 PrepRun（缺料贴随之更新）、库存不变、旧 run 钉死
- 校验失败（负数用量 / 不存在的原料或菜品 / 重复行）：全部保持保存前
"""
import json
import os
import tempfile

_db_path = os.path.join(tempfile.mkdtemp(prefix="kitprep_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SEED_ON_EMPTY"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine, PrepRun

Base.metadata.create_all(bind=engine)
client = TestClient(app)


@pytest.fixture()
def fx():
    db = SessionLocal()
    for m in (PrepRun, OrderLine, BomLine, KitchenOrder, Dish, Ingredient):
        db.query(m).delete()
    d1, d2 = Dish(code="D-HS", name="红烧肉套餐"), Dish(code="D-JT", name="鸡汤面")
    db.add_all([d1, d2]); db.flush()
    i1 = Ingredient(code="I-PR", name="五花肉", unit="kg", stock_qty=8.0)
    i2 = Ingredient(code="I-RC", name="大米", unit="kg", stock_qty=20.0)
    db.add_all([i1, i2]); db.flush()
    db.add_all([
        BomLine(dish_id=d1.id, ingredient_id=i1.id, qty_per_portion=0.25),
        BomLine(dish_id=d1.id, ingredient_id=i2.id, qty_per_portion=0.15),
        BomLine(dish_id=d2.id, ingredient_id=i2.id, qty_per_portion=0.2),
    ])
    o = KitchenOrder(code="KO-1", outlet="城西门店", status="open")
    db.add(o); db.flush()
    db.add_all([OrderLine(order_id=o.id, dish_id=d1.id, portions=10),
                OrderLine(order_id=o.id, dish_id=d2.id, portions=5)])
    db.commit()
    ids = {"d1": d1.id, "d2": d2.id, "i1": i1.id, "i2": i2.id, "o": o.id}
    yield db, ids
    db.close()


def bom_payload(ids, qty1=0.25, qty2=0.15, qty3=0.2):
    return {"lines": [
        {"dish_id": ids["d1"], "ingredient_id": ids["i1"], "qty_per_portion": qty1},
        {"dish_id": ids["d1"], "ingredient_id": ids["i2"], "qty_per_portion": qty2},
        {"dish_id": ids["d2"], "ingredient_id": ids["i2"], "qty_per_portion": qty3},
    ]}


def bom_snapshot(db):
    return sorted((b.dish_id, b.ingredient_id, b.qty_per_portion)
                  for b in db.query(BomLine).all())


def test_save_rewrites_tree_prep_and_shortages(fx):
    db, ids = fx
    client.post(f"/api/prep/run?order_id={ids['o']}")
    archived = db.query(PrepRun).order_by(PrepRun.id).first()
    archived_json = archived.result_json

    res = client.put("/api/bom", json=bom_payload(ids, qty1=1.0))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["line_count"] == 3
    assert [r["order_id"] for r in body["rewritten_runs"]] == [ids["o"]]

    # 树动了：新用量落库
    assert (ids["d1"], ids["i1"], 1.0) in bom_snapshot(db)
    # 单动了：新 run 按新用量展开（10 份 × 1.0 = 10），无需再点「生成备料单」
    latest = client.get(f"/api/prep/latest?order_id={ids['o']}").json()
    assert latest["id"] != archived.id
    need = {l["ingredient_id"]: l["need_qty"] for l in latest["prep_lines"]}
    assert need[ids["i1"]] == 10.0
    # 贴动了：缺料 = 10 − 8 = 2
    sh = client.get(f"/api/prep/shortages?order_id={ids['o']}").json()
    shortage = {s["ingredient_id"]: s["shortage"] for s in sh["shortages"]}
    assert shortage[ids["i1"]] == 2.0
    # 库存不被保存改小
    assert db.get(Ingredient, ids["i1"]).stock_qty == 8.0
    # 存档旧单钉死当时用量
    assert db.get(PrepRun, archived.id).result_json == archived_json


def test_save_negative_qty_rolls_back_everything(fx):
    db, ids = fx
    before_tree, before_runs = bom_snapshot(db), db.query(PrepRun).count()
    res = client.put("/api/bom", json=bom_payload(ids, qty1=-0.5))
    assert res.status_code == 422
    assert "负数" in res.text
    assert bom_snapshot(db) == before_tree
    assert db.query(PrepRun).count() == before_runs


def test_save_unknown_ingredient_rolls_back_everything(fx):
    db, ids = fx
    before_tree, before_runs = bom_snapshot(db), db.query(PrepRun).count()
    p = bom_payload(ids)
    p["lines"][0]["ingredient_id"] = 99999
    res = client.put("/api/bom", json=p)
    assert res.status_code == 422
    assert "不存在的原料" in res.text
    assert bom_snapshot(db) == before_tree
    assert db.query(PrepRun).count() == before_runs


def test_save_unknown_dish_rejected(fx):
    db, ids = fx
    before_tree = bom_snapshot(db)
    p = bom_payload(ids)
    p["lines"][0]["dish_id"] = 99999
    res = client.put("/api/bom", json=p)
    assert res.status_code == 422
    assert "不存在的菜品" in res.text
    assert bom_snapshot(db) == before_tree


def test_save_duplicate_line_rejected(fx):
    db, ids = fx
    p = bom_payload(ids)
    p["lines"].append(dict(p["lines"][0]))
    res = client.put("/api/bom", json=p)
    assert res.status_code == 422
    assert "重复" in res.text


def test_save_without_open_order_still_saves_tree(fx):
    db, ids = fx
    db.get(KitchenOrder, ids["o"]).status = "done"
    db.commit()
    res = client.put("/api/bom", json=bom_payload(ids, qty1=0.4))
    assert res.status_code == 200
    assert res.json()["rewritten_runs"] == []
    assert (ids["d1"], ids["i1"], 0.4) in bom_snapshot(db)
