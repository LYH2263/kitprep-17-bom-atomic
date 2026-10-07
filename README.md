# KitPrep 中央厨房 BOM 备料

按菜品 BOM 展开订单行、合并同原料需求，对照库存计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」「BOM」维护中央厨房出品与用料树；BOM 页可直接改每行用量并保存——保存会在一次事务里按新用量重写当前有效备料单与缺料贴（不做出库，库存结存不变；历史备料单保持存档不变）。用量为负数或指向不存在的原料/菜品时整单拒绝，树、单、贴均回退到保存前。
2. 在「订单」「库存」确认当日需求与现有库存。
3. 打开「备料单」展开合并原料需求。
4. 在「缺料」查看 need − stock 为正的原料。

## 开发与测试

```bash
docker compose exec api pytest -q
```
