# ParcelPilot 派送前 · 国内镜像

发货前 Excel / CSV 数据检查工具的静态镜像。原站保持不变：

<https://parcelpilot-dispatch-hyx.glacialbowl3.chatgpt.site/>

## 部署

```text
仓库：Hyxxt/portfolio
分支：main
根目录：留空
构建命令：npm run build:parcelpilot
输出目录：parcelpilot-dist
```

`parcelpilot-static` 是自包含的前端构建产物：HTML、CSS、Worker、SheetJS 解析器和 favicon，不依赖后端。文件只在浏览器本地处理。

## 边界

ParcelPilot 只检查格式与一致性，不验证真实地址、电话可接通性、物流可达性或实际订单状态；不发送订单或邮件。
