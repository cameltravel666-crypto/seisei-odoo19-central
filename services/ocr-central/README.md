# Central OCR Service

中央OCR服务 - 使用Gemini API进行发票和收据识别

## 概述

这是一个中央化的OCR服务，部署在独立服务器上，为所有Odoo实例（Staging和Production）提供OCR功能。

**部署位置**: 13.159.193.191:8180

## 架构

```
┌─────────────────────────────────────────────┐
│  中央OCR服务 (13.159.193.191:8180)          │
│  ├─ FastAPI应用 (Python 3.11)               │
│  ├─ Gemini 2.0 Flash API                    │
│  ├─ PostgreSQL数据库 (计费/配额)             │
│  └─ Docker部署                               │
└──────────────┬──────────────────────────────┘
               │
       ├───────┴──────────┐
       │                  │
  Staging Odoo       Production Odoo
  (13.231.24.250)    (54.65.127.141)
       │                  │
       └──────────┬───────┘
                  ↓
         调用 /api/v1/ocr/process
```

## 技术栈

- **Python**: 3.11
- **框架**: FastAPI
- **LLM**: Google Gemini 2.0 Flash Exp
- **数据库**: PostgreSQL 15
- **部署**: Docker + Docker Compose

## API端点

### 健康检查
```bash
GET /health
```

### OCR处理
```bash
POST /api/v1/ocr/process
Content-Type: application/json

{
  "image_data": "base64_encoded_image",
  "mime_type": "image/jpeg",
  "template_fields": [...],
  "tenant_id": "tenant_code",
  "prompt_version": "fast"  // or "full"
}
```

**响应**:
```json
{
  "success": true,
  "extracted": {
    "vendor_name": "供应商名称",
    "invoice_number": "INV-001",
    "date": "2026-02-02",
    "total": 15000,
    "line_items": [...]
  },
  "usage": {
    "used_this_month": 25,
    "free_quota": 30,
    "remaining": 5
  }
}
```

## 配置

### 环境变量

复制 `.env.example` 到 `.env` 并配置：

```env
# Gemini API密钥
GEMINI_API_KEY=your-gemini-api-key

# 服务认证密钥（与Odoo共享）
OCR_SERVICE_KEY=your-secure-service-key

# 数据库密码
OCR_DB_PASSWORD=secure-db-password

# 计费配置
OCR_FREE_QUOTA=30           # 每月免费额度
OCR_PRICE_PER_IMAGE=20      # 超额后每张图片价格（日元）
```

### Odoo配置

Odoo实例需要配置以下环境变量：

```env
# 在 odoo18-staging-rds/.env 或 odoo18-prod-rds/.env
OCR_SERVICE_URL=http://13.159.193.191:8180/api/v1
OCR_SERVICE_KEY=your-secure-service-key
```

## 部署

### 本地开发

```bash
cd services/ocr-central

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实值

# 启动服务
docker compose up -d

# 查看日志
docker compose logs -f ocr-service

# 测试健康检查
curl http://localhost:8180/health
```

### 部署到中央服务器 (13.159.193.191)

```bash
# 1. SSH到中央服务器
ssh ubuntu@13.159.193.191

# 2. 创建部署目录
mkdir -p ~/ocr-central
cd ~/ocr-central

# 3. 复制文件（从本地）
# 在本地执行：
scp -r services/ocr-central/* ubuntu@13.159.193.191:~/ocr-central/

# 4. 在服务器上配置环境变量
# SSH到服务器
cd ~/ocr-central
cp .env.example .env
nano .env  # 填入真实的API密钥和密码

# 5. 启动服务
docker compose up -d

# 6. 验证
docker ps | grep ocr
curl http://localhost:8180/health
```

### 使用部署脚本

创建自动化部署脚本：

```bash
# 在本地执行
./deploy_central_ocr.sh --server 13.159.193.191
```

## 计费模型

- **免费额度**: 每个租户每月30张图片
- **超额计费**: 超过免费额度后，每张图片20日元
- **计费周期**: 每月1日重置
- **数据存储**: PostgreSQL数据库记录每个租户的使用情况

## 监控

### 查看日志

```bash
# 应用日志
docker logs -f ocr-service

# 数据库日志
docker logs -f ocr-db
```

### 数据库访问

```bash
# 连接到PostgreSQL
docker exec -it ocr-db psql -U ocr -d ocr_service

# 查看租户使用情况
SELECT * FROM tenant_usage WHERE month = '2026-02';

# 查看OCR请求日志
SELECT * FROM ocr_requests ORDER BY created_at DESC LIMIT 10;
```

## 故障排除

### 问题: 健康检查失败

**检查**:
```bash
docker ps | grep ocr-service
docker logs ocr-service
```

**解决**: 重启服务
```bash
docker compose restart ocr-service
```

### 问题: Gemini API错误

**检查**: 验证API密钥
```bash
# 测试Gemini API
curl https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key=YOUR_API_KEY
```

### 问题: 数据库连接失败

**检查**:
```bash
docker logs ocr-db
docker exec -it ocr-db pg_isready -U ocr
```

## 安全

- ✅ API密钥仅在中央服务器配置，不暴露给租户
- ✅ 服务间通信使用认证密钥 (OCR_SERVICE_KEY)
- ✅ 数据库密码独立配置
- ✅ 仅监听内部网络（可配置）

## 开发流程

### 1. 本地开发
```bash
# 修改代码
vim services/ocr-central/main.py

# 本地测试
docker compose up --build

# 测试API
curl -X POST http://localhost:8180/api/v1/ocr/process \
  -H "Content-Type: application/json" \
  -H "X-Service-Key: test-key" \
  -d @test_request.json
```

### 2. 提交代码
```bash
git add services/ocr-central/
git commit -m "feat: update OCR service"
git push origin feature/update-ocr
```

### 3. 创建PR并合并

### 4. 部署到中央服务器
```bash
# 在中央服务器上
cd ~/ocr-central
git pull origin main
docker compose up -d --build
```

## 版本历史

- **v1.0.0** (2026-01-27): 初始版本，Gemini集成
- **v1.1.0** (2026-02-02): 纳入统一开发流程

## 相关链接

- **Odoo模块**: `/Users/taozhang/Projects/seisei-odoo-addons/odoo_modules/seisei/odoo_ocr_final/`
- **部署配置**: `/Users/taozhang/Projects/server-apps/services/ocr-central/`
- **Gemini API文档**: https://ai.google.dev/gemini-api/docs

## 联系方式

如有问题，请联系开发团队或查看项目文档。
