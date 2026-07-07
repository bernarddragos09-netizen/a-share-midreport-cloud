# A股中报日历云端部署版

这个目录用于部署“前端网站 + 云端后端”版本。部署后，别人打开一个网址即可使用页面，并且页面里的“抓取最新”“加载券商预测”都会请求云端 API，而不是你的电脑。

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
GET  /api/broker?code=600519
POST /api/update
```

## 注意

- Render 免费服务可能会休眠，第一次打开会慢一点。
- `POST /api/update` 会重新抓取上交所和东方财富数据，并重新生成云端首页，耗时可能较长。
- 如果上游网站临时限流，更新接口可能失败，稍后再点即可。
- 当前页面仍以沪市 2026 年中报预约披露为主，深市/北交所需要等对应数据源接入后再合并。
