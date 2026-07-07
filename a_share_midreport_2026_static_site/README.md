# A Share 2026 Midreport Static Site

这个目录是可直接发布的静态网站。

## GitHub Pages 发布方法

1. 新建一个 GitHub 仓库。
2. 把本目录里的 `index.html` 上传到仓库根目录。
3. 打开仓库 `Settings` -> `Pages`。
4. `Build and deployment` 选择 `Deploy from a branch`。
5. Branch 选择 `main`，目录选择 `/root`，保存。
6. 等几十秒，GitHub 会给你一个可分享的网址。

这个静态版不依赖你电脑上的 Python 服务；券商预测数据已预先写入页面。
如果以后要更新数据，在本地重新运行：

```bash
python build_static_site.py
```
