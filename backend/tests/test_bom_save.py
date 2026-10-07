"""定额树保存：树叶子/需求列/缺料贴必须一起过或一起停，且保存不是出库。"""
import json

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import (
    BomLine, Dish, Ingredient, KitchenOrder, OrderLine, PrepRun,
)
from app.services.prep_run_service import build_result, dumps


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    d1 = Dish(code="D1", name="菜一", portion_unit="份")
    d2 = Dish(code="D2", name="菜二", portion_unit="份")
    db.add_all([d1, d2]); db.flush()
    i1 = Ingredient(code="I1", name="肉", unit="kg", stock_qty=5.0)
    i2 = Ingredient(code="I2", name="米", unit="kg", stock_qty=20.0)
    db.add_all([i1, i2]); db.flush()
    db.add_all([
        BomLine(dish_id=d1.id, ingredient_id=i1.id, qty_per_portion=0.2),
        BomLine(dish_id=d1.id, ingredient_id=i2.id, qty_per_portion=0.1),
        BomLine(dish_id=d2.id, ingredient_id=i1.id, qty_per_portion=0.3),
    ])
    order = KitchenOrder(code="KO-1", outlet="门店", status="open")
    db.add(order); db.flush()
    db.add_all([
        OrderLine(order_id=order.id, dish_id=d1.id, portions=10),
        OrderLine(order_id=order.id, dish_id=d2.id, portions=5),
    ])
    db.commit()
    self_ids = type("IDs", (), {"d1": d1.id, "d2": d2.id, "i1": i1.id, "i2": i2.id, "order": order.id})()
    db.close()
    with TestClient(app) as c:
        yield c, self_ids


def _active_run(db, order_id):
    return db.query(PrepRun).filter_by(order_id=order_id, status="active").order_by(PrepRun.id.desc()).first()


def test_save_rewrites_tree_demand_and_shortage_together(client):
    c, ids = client
    # 先有一张当前有效备料单：肉需 10*0.2+5*0.3=3.5，库存 5 -> 无缺料
    r = c.post(f"/api/prep/run?order_id={ids.order}")
    assert r.status_code == 200
    assert r.json()["shortages"] == []

    # 新用量：菜一 肉 0.2->1.0，肉需 10*1.0+5*0.3=11.5，库存 5 -> 缺 6.5
    payload = {"lines": [
        {"dish_id": ids.d1, "ingredient_id": ids.i1, "qty_per_portion": 1.0},
        {"dish_id": ids.d1, "ingredient_id": ids.i2, "qty_per_portion": 0.1},
        {"dish_id": ids.d2, "ingredient_id": ids.i1, "qty_per_portion": 0.3},
    ]}
    r = c.put("/api/bom", json=payload)
    assert r.status_code == 200, r.text

    # 树叶子已是新用量
    tree = { (b["dish_id"], b["ingredient_id"]): b["qty_per_portion"] for b in c.get("/api/bom").json()}
    assert tree[(ids.d1, ids.i1)] == 1.0

    # 当前有效备料单的需求列与缺料贴一次保存里一起被重写
    db = SessionLocal()
    try:
        data = json.loads(_active_run(db, ids.order).result_json)
        by_id = {l["ingredient_id"]: l for l in data["prep_lines"]}
        assert by_id[ids.i1]["need_qty"] == 11.5
        short = {s["ingredient_id"]: s for s in data["shortages"]}
        assert ids.i1 in short and short[ids.i1]["shortage"] == 6.5
    finally:
        db.close()

    # 缺料贴接口也同步反映新缺料
    res = c.get(f"/api/prep/shortages?order_id={ids.order}").json()
    assert {s["ingredient_id"] for s in res["shortages"]} == {ids.i1}


def test_save_is_not_outbound_stock_untouched(client):
    c, ids = client
    c.post(f"/api/prep/run?order_id={ids.order}")
    before = {i["id"]: i["stock_qty"] for i in c.get("/api/inventory").json()}
    r = c.put("/api/bom", json={"lines": [
        {"dish_id": ids.d1, "ingredient_id": ids.i1, "qty_per_portion": 9.0},
    ]})
    assert r.status_code == 200
    after = {i["id"]: i["stock_qty"] for i in c.get("/api/inventory").json()}
    # 无论需求/缺料多大，账面结存不得被这次保存改小
    assert after == before


def test_negative_qty_entire_save_rolled_back(client):
    c, ids = client
    r = c.put("/api/bom", json={"lines": [
        {"dish_id": ids.d1, "ingredient_id": ids.i1, "qty_per_portion": -0.2},
    ]})
    assert r.status_code == 422
    # 树停在保存前
    rows = c.get("/api/bom").json()
    assert {b["qty_per_portion"] for b in rows} == {0.2, 0.1, 0.3}
    # 单也停在保存前：肉需 3.5 无缺料
    res = c.get(f"/api/prep/latest?order_id={ids.order}").json()
    by_id = {l["ingredient_id"]: l for l in res["prep_lines"]}
    assert by_id[ids.i1]["need_qty"] == 3.5
    assert res["shortages"] == []


def test_missing_ingredient_entire_save_rolled_back(client):
    c, ids = client
    c.post(f"/api/prep/run?order_id={ids.order}")
    r = c.put("/api/bom", json={"lines": [
        {"dish_id": ids.d1, "ingredient_id": 9999, "qty_per_portion": 0.2},
    ]})
    assert r.status_code == 422
    # 树没动（全量替换不得把旧树删空后提交）
    assert len(c.get("/api/bom").json()) == 3
    # 单没动：仍是原需求
    res = c.get(f"/api/prep/latest?order_id={ids.order}").json()
    assert {l["ingredient_id"]: l["need_qty"] for l in res["prep_lines"]}[ids.i1] == 3.5


def test_missing_dish_entire_save_rolled_back(client):
    c, ids = client
    r = c.put("/api/bom", json={"lines": [
        {"dish_id": 8888, "ingredient_id": ids.i1, "qty_per_portion": 0.2},
    ]})
    assert r.status_code == 422
    assert len(c.get("/api/bom").json()) == 3


def test_duplicate_line_rejected(client):
    c, ids = client
    r = c.put("/api/bom", json={"lines": [
        {"dish_id": ids.d1, "ingredient_id": ids.i1, "qty_per_portion": 0.2},
        {"dish_id": ids.d1, "ingredient_id": ids.i1, "qty_per_portion": 0.3},
    ]})
    assert r.status_code == 422
    assert len(c.get("/api/bom").json()) == 3


def test_archived_run_pinned_to_old_usage(client):
    c, ids = client
    # 第一张单（用量 0.2）随后被新生成的单存档
    first = c.post(f"/api/prep/run?order_id={ids.order}").json()
    first_id = first["id"]
    c.post(f"/api/prep/run?order_id={ids.order}")  # 首单转 archived

    # 保存新用量，肉需变为 11.5
    r = c.put("/api/bom", json={"lines": [
        {"dish_id": ids.d1, "ingredient_id": ids.i1, "qty_per_portion": 1.0},
        {"dish_id": ids.d1, "ingredient_id": ids.i2, "qty_per_portion": 0.1},
        {"dish_id": ids.d2, "ingredient_id": ids.i1, "qty_per_portion": 0.3},
    ]})
    assert r.status_code == 200

    db = SessionLocal()
    try:
        archived = db.get(PrepRun, first_id)
        assert archived.status == "archived"
        data = json.loads(archived.result_json)
        # 旧单钉死当时用量：肉需仍是 3.5，不被这次保存改回去
        by_id = {l["ingredient_id"]: l for l in data["prep_lines"]}
        assert by_id[ids.i1]["need_qty"] == 3.5
        assert data["shortages"] == []
        # 当前有效单是新用量
        active = _active_run(db, ids.order)
        assert active.id != first_id
        active_data = json.loads(active.result_json)
        assert {l["ingredient_id"]: l["need_qty"]
                for l in active_data["prep_lines"]}[ids.i1] == 11.5
    finally:
        db.close()
