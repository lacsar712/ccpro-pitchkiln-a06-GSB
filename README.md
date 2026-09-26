# PitchKiln-01 · 灶台值守看板

Django 5 + PostgreSQL：灶台瓦片看板 + 右侧抽屉探针时间线，无 Vue/React SPA。

## 技术栈

- Django 5、PostgreSQL
- Session 登录
- HTMX：局部刷新灶台网格与抽屉
- Docker Compose：`web` + `db`

## 端口与数据库

| 服务 | 端口 |
|------|------|
| Web  | **4710** |
| Postgres | **6110**（容器内 5432） |

数据库账号：`pitchkiln` / `pitchkiln` / 库名 `pitchkiln`

## 快速启动

```bash
cd PitchKiln/PitchKiln-01
docker compose up --build -d
```

浏览器打开：http://localhost:4710

演示账号：

- `admin` / `123456`（超级用户）
- `worker` / `123456`（普通用户）

容器启动时会自动：`migrate` → `seed_data` → `collectstatic` → `gunicorn`

## 本地开发（可选）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 确保本机 Postgres 监听 6110，或先 docker compose up -d db
set POSTGRES_HOST=localhost
set POSTGRES_PORT=6110
python manage.py migrate
python manage.py seed_data
python manage.py runserver 0.0.0.0:4710
```

## 业务模型

1. **ResinLot（来脂批）**：`lotCode`、`originPlace`、`arrivalKg`、`receivedAt`
2. **FireHearth（灶台）**：`lane`、`tag`（唯一）、`resinGrade`、相位 `cold|charging|ramping|holding|drawing`
3. **CookRun（熬制值守）**：归属灶台与来脂批、`openedAt`、`closedAt`（可空）、`targetSoftPointC`
4. **SoftPointProbe（软化点探针）**：归属值守、`sampledAt`、`softPointC`、`samplerName`
5. **SoftPointRecheck（软化复核）**：归属值守、`recheckNo`（复核号，从 1 起，同一值守内唯一）、`softPointC`（复核软化点）、`checkedAt`（复核时刻）、`checkerName`（复核人）。已收灶的值守拒绝登记，仅未收灶值守可写。

**业务规则**：将灶台相位切到 `drawing`（出胶）时，除原有探针门槛外另核软化复核链，全部通过才放行：

1. 进行中的 CookRun 至少有一条 SoftPointProbe 的 `softPointC ≤ 95`；
2. 复核号从 1 起连续的复核链不少于 3 条；
3. 链内相邻复核软化点的绝对差 **≤ 4℃**（差限 4℃）；
4. 链首最新复核时刻晚于最新探针时刻。

通过后自动把最新复核软化点落一条探针（取样人标记 `复核#N·姓名`），供探针时间线可见；任一条件不满足即挡下。因落针时刻等于最新复核时刻，再次切入出胶需要更新的复核。逻辑集中在 `apps/kiln/services/floor_rules.py` 的 `assert_can_enter_drawing`，相位表单与改相位入口共用同一来源（同源校验），落针仅在改相位入口 `change_hearth_phase` 内执行。

## 界面

- 首页：**灶台值守看板** — 左侧班次条 + 按过道排布的灶台瓦片；点瓦片打开右侧抽屉（值守、探针时间线、软化复核条数与连续链长、改相位 / 登记探针 / 开灶）
- 次页：**软化复核**（班次条「复」）— 复核登记（仅未收灶值守可选）+ 复核卡片时间线
- 次页：**来脂批** — 卡片时间线，非宽表 CRUD

## 种子数据

```bash
python manage.py seed_data
```

幂等：已有灶台则只保证账号存在。样例地名仅用「松脂坳 / 桐油坑」系。其中「坑火-西一」值守预置两条软化复核（#1、#2），链长不足三条，用于演示出胶复核门槛；在「复」页补登 #3（与 #2 差 ≤4℃、时刻晚于最新探针）后即可放行并自动落针。

## 目录结构

```
PitchKiln-01/
  manage.py
  requirements.txt
  Dockerfile
  entrypoint.sh
  docker-compose.yml
  config/
  apps/kiln/          # 模型、视图、floor_rules、种子
  templates/floor/    # 值守看板 + 抽屉
  templates/resin/    # 来脂批时间线
  static/css/         # 值守台 ops-console 样式
```
