# Aster Live · 可用的询价 Demo

这是 Aster Precision 演示站的**功能性版本**。前端沿用原有设计，新增：

- 真实 RFQ 提交接口，记录写入数据库
- 密码保护的询价后台：查看、筛选、标记状态、删除、导出 CSV
- 基本防刷：频率限制、蜜罐字段、字段校验
- 可选邮件通知（Resend）
- 本地 JSON 存储；生产环境使用 PostgreSQL

> Aster Precision 是虚构品牌，所有产品、价格、认证和公司信息均为演示。请不要把真实客户资料或机密图纸提交到这个 Demo。要用于真实业务，必须替换品牌和内容，并补齐正式隐私政策、备份和运营流程。

## 本地运行

```powershell
cd D:\Claude\aster-live
npm install
$env:ADMIN_PASSWORD="换成一个长密码"
$env:DATA_FILE=".\data\rfqs.json"
npm start
```

打开：

- 前台：<http://localhost:3000/request-quote/>
- 后台：<http://localhost:3000/admin>

本地默认使用 `data/rfqs.json`，该目录不会提交到 Git。

## 测试

```powershell
npm test
```

测试使用临时 JSON 文件，不会碰本地数据。

## 生产环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `DATABASE_URL` | 生产必填 | PostgreSQL 连接串；带 `sslmode=require` 时会启用 TLS |
| `ADMIN_PASSWORD` | 是 | 后台登录密码；生产环境不设置会拒绝启动 |
| `ADMIN_SESSION_SECRET` | 建议 | 签名后台 Cookie；不设时回退用 `ADMIN_PASSWORD` |
| `NODE_ENV` | 建议 | 生产填 `production` |
| `ALLOWED_ORIGINS` | 可选 | 允许跨域提交 RFQ 的前端源，逗号分隔；默认包含 Maozi 静态站域名 |
| `RESEND_API_KEY` | 可选 | 新询价邮件通知 |
| `NOTIFY_EMAIL` | 可选 | 接收通知的邮箱，多个用逗号分隔 |
| `FROM_EMAIL` | 可选 | Resend 发件人，默认 `Aster Demo <onboarding@resend.dev>` |

生产环境没有 `DATABASE_URL` 会直接启动失败，避免把数据写进临时磁盘。

## 部署到 Render（免费 Web + PostgreSQL）

1. 创建免费 PostgreSQL，拿到连接串。
2. 新建 Web Service：

```text
仓库：https://github.com/Hyxxt/portfolio
分支：main
根目录：aster-live
构建命令：npm install
启动命令：npm start
健康检查：/api/health
```

3. 设置环境变量：`DATABASE_URL`、`ADMIN_PASSWORD`、`ADMIN_SESSION_SECRET`、`NODE_ENV=production`。
4. 部署后访问 `/admin`，用 `ADMIN_PASSWORD` 登录。

Render 免费 PostgreSQL 有有效期限制；长期使用请换成付费实例或 Neon/Supabase 等托管库。

## 部署到帽子云（国内）

新建 **Web 应用**，Buildpack 构建：

```text
仓库：Hyxxt/portfolio
分支：main
根目录：aster-live
构建命令：npm install
启动命令：npm start
```

同一个项目里再建 PostgreSQL，把内网连接串填到 Web 应用的 `DATABASE_URL`。Web 应用和 PostgreSQL 都按规格计费，创建前先看控制台价格。

## 前端如何调用接口

`public/wp-content/themes/aster-precision/assets/site.js` 会读取页面里的：

```html
<meta name="aster-api-base" content="">
```

留空表示同源调用 `/api/rfq`。如果前端放在另一个域名（例如 Maozi 静态站），把 `content` 填成 Live 应用的地址，并把该前端域名加入 `ALLOWED_ORIGINS`。

## 安全与限制

- 后台 Cookie 为 `HttpOnly` + `SameSite=Strict`，生产环境自动加 `Secure`。
- 登录 15 分钟 6 次、询价 10 分钟 12 次的单实例内存限流；实例重启后重置。
- 数据表没有保存银行卡、密码或文件；表单明确要求不要提交机密信息。
- CSV 导出对以 `= + - @` 开头的单元格做了公式注入防护。
- 这是单管理员 Demo，不是多租户 CRM；上真实业务前需要加账号体系、审计、备份和合规流程。
