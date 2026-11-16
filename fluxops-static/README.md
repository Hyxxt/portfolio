# FluxOps 流序 · 国内静态镜像

这是 FluxOps CSV 双表核对工具的**纯静态版本**，用于国内访问。原始站点保持不变：

<https://fluxops-data-workbench-hyx.glacialbowl3.chatgpt.site/>

## 说明

- 工具仍然完全在浏览器本地处理文件，没有上传接口，不需要后端。
- 构建产物来自 `D:\CODEX\tradeops-data-workbench` 的公开产品页，使用 Vite + React 单独打包，去掉了原项目的 Cloudflare Workers / RSC 运行时。
- `index.html`、`assets/` 和 `favicon.svg` 是已构建文件，不包含源文件。
- 源工程和核对逻辑仍在 `D:\CODEX\tradeops-data-workbench`；核心逻辑是 `lib/reconcile.ts`。

## 帽子云部署

新建静态网站：

```text
仓库：Hyxxt/portfolio
分支：main
根目录：留空
构建命令：npm run build:fluxops
输出目录：fluxops-dist
```

## 本地验证

```powershell
npm run build:fluxops
```

然后用任意静态服务器打开 `fluxops-dist/`。
