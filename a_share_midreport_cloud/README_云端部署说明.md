# A股中报日历云端部署版

这个目录用于部署“前端网站 + 云端后端”版本。部署后，别人打开一个网址即可使用页面，并且页面里的“抓取最新”“加载券商预测”都会请求云端 API，而不是你的电脑。

股票筛选器的 ROE、毛利率、资产负债率、经营现金流和股息率由 AKShare 批量抓取后写入服务器快照，页面不会在用户访问时直接请求第三方网站。

## 推荐部署：Render

1. 把整个项目文件夹上传到 GitHub 仓库。
2. 打开 Render，选择 `New` -> `Blueprint`。
3. 选择这个 GitHub 仓库。
4. Render 会读取 `a_share_midreport_cloud/render.yaml`。
5. 创建服务后等待构建完成。
6. Render 会给你一个类似这样的公网网址：

```text
https://a-share-midreport-cloud.onrender.com
```

打开这个网址就是完整网站。

## 如果不用 Blueprint，手动创建 Web Service

Build Command:

```bash
pip install -r a_share_midreport_cloud/backend/requirements.txt && python build_cloud_frontend.py
```

Start Command:

```bash
uvicorn a_share_midreport_cloud.backend.app:app --host 0.0.0.0 --port $PORT
```

## API

```text
GET  /api/health
GET  /api/home
GET  /api/search?q=600519
GET  /api/screener?roe_min=10&cashflow=positive
GET  /api/stock/600519
GET  /api/broker?code=600519
POST /api/update
```

## AKShare 财务指标

本地单独刷新 AKShare 缓存：

```bash
python fetch_akshare_metrics.py
```

默认先抓取 2026 年一季报作为全市场基准，再用已经披露的 2026 年中报覆盖对应公司；分红收益率使用 2025 年报和最新 2026 年中报数据。缓存保存在：

```text
a_share_midreport_cloud/data/stock_snapshot.json
```

当前接入字段：

```text
营业收入及同比
归母净利润及同比
ROE
销售毛利率
资产负债率
经营、投资和筹资现金流
股息率
AKShare行业
```

## 注意

- Render 免费服务可能会休眠，第一次打开会慢一点。
- `POST /api/update` 会更新披露日历、行情快照和 AKShare 财务指标，通常需要约 3 至 5 分钟。
- 如果上游网站临时限流，更新接口可能失败，稍后再点即可。
- 当前页面覆盖沪深 A 股；AKShare 数据会保留明确的报告期，未披露中报的公司使用最新可用一季报，不会伪装成中报数据。
