# FastAPI + Docker + Nginx (HTTPS) + SQLite + Alipay（官方 AOP SDK）

## 一键启动概览
- 使用环境变量驱动配置，支持 `${DOMAIN}` 占位。
- Nginx 读取宿主机 `/etc/letsencrypt` 证书，自动续期后可热加载。
- 集成支付宝网页支付（Page Pay），覆盖下单、同步回跳与异步通知。
- 提供 Linux Bash 与 Windows PowerShell 脚本，支持启动、停止与环境初始化。

## 目录
- `app/`：FastAPI 应用
- `nginx/`：Nginx 镜像与模板
- `Dockerfile`：构建 app 镜像
- `docker-compose.yml`：一键编排
- `.env.example`：环境变量示例
- `scripts/`：一键启动、停止与环境初始化脚本
- 宿主机证书路径：`/etc/letsencrypt`（以只读方式挂载进容器）

## 环境变量（`.env`）
- `DOMAIN=your.domain.com`
- `SERVER_NAME=${DOMAIN}`
- `BASE_URL=https://${DOMAIN}`
- `SSL_CERT_PATH=/etc/letsencrypt/live/${DOMAIN}/fullchain.pem`
- `SSL_KEY_PATH=/etc/letsencrypt/live/${DOMAIN}/privkey.pem`
- `APP_ENV`, `APP_HOST`, `APP_PORT`, `APP_NAME`
- `DATABASE_URL=sqlite:////data/app.db`
- `CORS_*`（可选）
- 支付宝相关变量见后续章节

> 注意：项目在开发与生产环境均默认使用 SQLite。因 SQLite 为单文件数据库，建议启用 WAL 模式并控制并发写入；若业务高并发，可结合读写队列或按需迁移至外部数据库。

## 自动生成 `.env`
- Linux / macOS：
  ```bash
  cp -n .env.example .env || true
  ```
- Windows PowerShell：
  ```powershell
  if (-Not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
  ```
- 如需覆盖已有配置，可先手动备份 `.env` 再重新执行上述命令。

## 支付宝配置
- `ALIPAY_APP_ID`：应用 APPID
- `ALIPAY_DEBUG`：`true`（沙箱）或 `false`（生产）
- `ALIPAY_GATEWAY`：
  - 沙箱：`https://openapi-sandbox.dl.alipaydev.com/gateway.do`
  - 生产：`https://openapi.alipay.com/gateway.do`
- 回调路径（基于 `BASE_URL`）：
  - `ALIPAY_NOTIFY_PATH=/pay/notify`
  - `ALIPAY_RETURN_PATH=/pay/return`
- 密钥注入（任选其一）：
  - 直接设置 PEM 内容：`ALIPAY_APP_PRIVATE_KEY_PEM`、`ALIPAY_PUBLIC_KEY_PEM`（多行以 `\n` 转义）
  - 挂载路径（推荐，复用 `/etc/letsencrypt`）：
    - `ALIPAY_APP_PRIVATE_KEY_PATH=/etc/letsencrypt/alipaycerts/alipay_private_key.pem`
    - `ALIPAY_PUBLIC_KEY_PATH=/etc/letsencrypt/alipaycerts/alipay_public_key.pem`

> 为确保容器可读取支付宝密钥，请在宿主机创建 `/etc/letsencrypt/alipaycerts` 并设置合适的读权限（例如 640），之后再挂载到容器。

## Nginx 实现要点
- 建议在 `docker-compose.yml` 中将反向代理服务命名为 `nginx`，使用 `nginx:1.25-alpine` 等轻量镜像。
- Nginx 容器与 FastAPI 应用共享自定义网络（如 `backend`），使用内网域名或服务名反向代理 `app` 容器。
- 核心模板位于 `nginx/conf.d/app.conf`，推荐配置：
  - `listen 443 ssl http2;` 与 `listen 80;`（自动跳转）
  - `proxy_set_header Host $host;` 等转发请求头
  - 将 `/health` 暴露为无鉴权健康检查路径
  - 启用 `gzip`、`client_max_body_size` 等必要指令
- Docker Compose 示例（片段）：
  ```yaml
  services:
    nginx:
      image: nginx:1.25-alpine
      volumes:
        - ./nginx/conf.d:/etc/nginx/conf.d:ro
        - /etc/letsencrypt:/etc/letsencrypt:ro
      depends_on:
        - app
      ports:
        - "80:80"
        - "443:443"
      networks:
        - backend
    app:
      build: .
      networks:
        - backend
  networks:
    backend:
      driver: bridge
  ```
- 保持 `docker compose exec nginx nginx -s reload` 可用，后续证书续期钩子将复用此命令。

## SSL 证书与自动续期
- 证书来源：宿主机使用 certbot / Let's Encrypt 申请与续期。
- 宿主机默认目录：
  - `/etc/letsencrypt/live/${DOMAIN}/fullchain.pem`
  - `/etc/letsencrypt/live/${DOMAIN}/privkey.pem`
- Compose 已将宿主机 `/etc/letsencrypt` 以只读方式挂载进 Nginx 容器。
- Let's Encrypt 续期后建议触发 Nginx reload，示例 deploy-hook：
  ```bash
  # /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
  #!/bin/sh
  set -e
  cd /path/to/project
  docker compose exec nginx nginx -s reload || true
  ```
- 运行 deploy-hook 前，请确认 `nginx` 服务对应的容器已创建并处于运行状态，否则 `exec` 会失败。

## 支付宝：沙箱 vs 生产
- 需要调整的变量：
  - `ALIPAY_GATEWAY`
  - `ALIPAY_DEBUG`
  - `ALIPAY_APP_ID` 与密钥
  - `BASE_URL` 与 SSL 证书
  - 开放平台回调配置（异步通知、同步回跳）
- 建议：
  - 回调处理保持幂等，校验金额与订单号映射。
  - 设置日志与告警，及时监控异步通知失败。

## 一键脚本
- Linux：
  - 启动：`bash scripts/start.sh`
  - 停止：`bash scripts/stop.sh`
- Windows PowerShell：
  - 启动：`pwsh -File scripts/start.ps1`
  - 停止：`pwsh -File scripts/stop.ps1`

## 启动后测试
- 健康检查（HTTP 80 -> 301 -> HTTPS 443）：`https://${DOMAIN}/health`
- 创建订单（PC 网页支付）：
  - `POST https://${DOMAIN}/pay/create`
  - 请求体示例：`{"subject": "测试商品", "total_amount": "0.10", "channel": "pc"}`
  - 响应返回 `pay_url`，浏览器打开跳转至沙箱或生产收银台。
- 回调：
  - 同步回跳：`GET ${BASE_URL}${ALIPAY_RETURN_PATH}`
  - 异步通知：`POST ${BASE_URL}${ALIPAY_NOTIFY_PATH}`，服务端需返回纯文本 `success`。

## 说明
- 异步通知为最终支付结果；同步回跳仅用于展示。
- SQLite 文件持久化于命名卷 `app_data`（容器内 `/data/app.db`）。
- Nginx 默认启用 HTTP/2 与 HSTS，请确保证书有效并及时续期。
