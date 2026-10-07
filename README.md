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

1. 在「菜品」「BOM」维护中央厨房出品与用料树。
2. 在「订单」「库存」确认当日需求与现有库存。
3. 打开「备料单」展开合并原料需求。
4. 在「缺料」查看 need − stock 为正的原料。

### 定额树保存用量（`PUT /api/bom`）

- 树叶子、当前有效备料单的需求列、缺料贴在**同一事务**里按新用量一起重写，一起过或一起回滚——不存在「栏位先存、再等人点生成备料单」。
- 用量为负数、指向不存在的原料/菜品、同菜品同原料重复时，整笔退回（HTTP 422），树、单、贴都停在保存前。
- 保存**不是出库**：`stock_qty` 账面结存不被改动。
- 重新生成备料单时，旧单自动归档（`archived`），其快照钉死当时用量，保存定额不会改写历史。

## 开发与测试

```bash
docker compose exec api pytest -q
```
