# 黄佑雄 · AI 全栈开发作品集

2027 届全日制大专在读，方向 AI 全栈开发 / AI 应用 / 数据分析，在广州白云，每周可到岗 5 天。

作品集包含 5 个已上线的 Next.js 全栈项目（AI 报价、RAG 知识库、AI 求职匹配、订单跟进、理赔通），以及 pandas 广告数据分析、Python 自动化、影刀 RPA、Coze 工作流等原型。另有一个 QMS 来料异常产品设计案例（PRD、业务泳道图、可交互原型），入口 `/qms/`。关键金额、判定、匹配分写在确定性代码里，模型只负责理解语言，结果可复核、能演示、有测试。

- 在线作品集（国内直连）：<https://huangyouxiong-10m3k3ol.maozi.io/>
- 海外镜像：<https://huangyouxiong.pages.dev/>
- GitHub：<https://github.com/Hyxxt>

## 本地预览

```bash
npm run build
npx serve dist
```

或直接用浏览器打开 `index.html`。

## 部署

`npm run build` 会把 `index.html`、`img/`、`resume.pdf` 等复制到 `dist/`，静态托管平台发布 `dist/` 即可。

## 新增美妆电商运营案例

澄光美妆运营台：AI概念素材、图文草稿、指标诊断、活动贡献利润、工单与报告导出。全部经营数据为模拟。14项计算测试、12项浏览器验收通过。

- 作品集内入口：`beauty-ops/`
- 独立站：<https://chengguang-beauty-ops.onrender.com>
- 独立仓库：<https://github.com/Hyxxt/chengguang-beauty-ops>

## 新增 QMS 产品设计案例

面向制造业来料检验的异常处理设计：六个状态、四类角色，覆盖退回补充、评审驳回和复验不合格重开。交付 PRD、业务泳道图与可交互 HTML 原型，全部为自主设计练习与演示数据。

- 作品集内入口：`qms/`
- PRD 网页版：`qms/prd.html`（含 Word / Markdown 下载）
- 独立站：<https://qms-portfolio.pages.dev/>
