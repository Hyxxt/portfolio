# Northform · 高级 B2B 独立站 Demo

这是为作品集制作的**虚构精密制造 B2B 品牌站**，英文为主、可切中文。

- 首页：3D 可交互轴承组件、爆炸视图、滚动叙事、材料/工艺展示
- 产品：Halo 01 / Axis 02 / Frame 03，三个可配置产品页
- 配置器：材料、表面、数量、公差，实时更新 3D 模型和摘要
- RFQ：生成演示询价编号和 JSON 简报，数据只保存在浏览器本地
- 技术：React 19 + TypeScript + Vite + React Three Fiber + Drei + Motion

## 来源

源工程在 `D:\Claude\northform`。这里保存的是构建后的纯静态文件（`index.html`、`assets/`、`og.png` 等），部署时不需要安装 React/Three。

## 帽子云部署

新建静态网站：

```text
仓库：Hyxxt/portfolio
分支：main
根目录：留空
构建命令：npm run build:northform
输出目录：northform-dist
```

## 边界

NORTHFORM 是虚构品牌，产品、规格、公差、交期、设备和检测描述均为演示，不代表真实认证、客户、产能或报价。RFQ 只在浏览器本地保存，不会发送到服务器。
