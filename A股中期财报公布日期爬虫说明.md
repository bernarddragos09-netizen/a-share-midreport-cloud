# A股中期财报公布日期爬虫说明

## 目标

统计 A 股中期/半年报公布日期：哪些日期有公司公布财报、每天公布多少家。

本项目使用巨潮资讯网“预约披露”页面背后的公开请求接口，抓取字段包括股票代码、股票简称、报告期、首次预约日期、变更日期和实际披露日期。

## 文件

- `fetch_a_share_midreport_2026.py`：爬虫和统计脚本。
- `a_share_midreport_output/`：脚本运行后生成的结果目录。
- `detail_*.csv`：公司级明细。
- `daily_count_*.csv`：按日期统计的每日公布家数。
- `report_*.md`：Markdown 汇总报告。
- `report_*.html`：可展开的网页报告，点击“展开企业列表”可以查看当天公布业绩的企业名称和股票代码。

## 运行方法

在脚本所在文件夹打开 PowerShell，运行：

```powershell
python fetch_a_share_midreport_2026.py
```

如果看到 `>>>`，说明你在 Python 交互模式里，需要先输入：

```python
exit()
```

再运行上面的 PowerShell 命令。

## 常用参数

默认自动选择巨潮当前可用的最新“半年报/中报”报告期。若要指定报告期：

```powershell
python fetch_a_share_midreport_2026.py --section 2025-06-30
```

默认统计“实际披露日期”。若要统计“首次预约日期”：

```powershell
python fetch_a_share_midreport_2026.py --date-field first
```

若要统计“最终可用日期”，即优先实际披露日期，若没有实际披露则取最后一次预约/变更日期：

```powershell
python fetch_a_share_midreport_2026.py --date-field final
```

市场范围默认是 `szsh`，代表深沪京全部 A 股。可选值包括：

- `szsh`：深沪京
- `sz`：深市
- `sh`：沪市
- `bj`：北交所
- `cyb`：创业板
- `kcb`：科创板

示例：

```powershell
python fetch_a_share_midreport_2026.py --section 2025-06-30 --market szsh --date-field actual
```

运行完成后，打开 `a_share_midreport_output` 目录里的 `report_*.html` 文件，就能看到可展开的统计页面。每个日期对应一行，家数下面有“展开企业列表”按钮，展开后显示当天所有公司，格式为“股票代码 + 股票简称”。

## 2026 年即将到来的中报

如果要抓即将披露的 2026 年中报预约时间，运行：

```powershell
python fetch_2026_midreport_upcoming_sse.py
```

当前这个脚本抓取上交所已经发布的沪市 2026 年半年报（中报）预约披露表，输出目录为 `a_share_midreport_2026_upcoming_sse/`，其中 `report_sse_2026_midreport.html` 是可展开网页报告。

截至 2026-06-27，巨潮当前可选报告期仍未包含 `2026-06-30`，深市/北交所完整预约表也需要等待官方数据源放出后再合并。

`report_sse_2026_midreport.html` 中，每家公司名称是可点击按钮。展开后会显示营业总收入、归母净利润、扣非归母净利润及同比增长率；同比为正显示红色，为负显示绿色。2026 年中报正式披露前，脚本会优先显示东方财富业绩预告中的区间数据；没有正式披露或预告的项目显示“待披露”。

## 统计口径

脚本支持以下统计日期字段：

- `actual`：实际披露日期，适合统计“真实公布日期”。
- `first`：首次预约日期，适合统计公司最初计划公布日期。
- `change1`：第一次变更日期。
- `change2`：第二次变更日期。
- `change3`：第三次变更日期。
- `final`：实际披露优先，否则取最后一次预约/变更日期。

## 注意事项

截至 2026-06-27，巨潮当前可选报告期中尚未出现 `2026半年报`，最新可用半年报期为 `2025-06-30 / 2025半年报`。所以默认自动模式会抓取最新可用半年报，而不是还未发布的 2026 半年报。

网络请求可能受网站访问速度影响，如果中途失败，可以重新运行脚本。脚本不依赖第三方 Python 包，只需要已安装 Python。
