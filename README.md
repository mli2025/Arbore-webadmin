# Web管理界面部署指南

## 📋 文件结构

```
web-admin/
├── backend/          # FastAPI后端
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
├── frontend/         # Vue 3前端
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf
│   ├── index.html
│   └── src/
│       ├── main.js
│       ├── App.vue
│       └── components/
│           ├── ServicesView.vue
│           ├── ResourcesView.vue
│           └── LogsView.vue
└── README.md
```

## 🚀 部署步骤

### 1. 上传文件到服务器

在本地Windows机器上执行：

```powershell
# 进入项目目录
cd E:\Arbore\console

# 使用SCP上传web-admin目录到服务器
scp -r web-admin arbore@192.168.163.134:/home/arbore/console/

# 上传nginx配置（如果还没有）
scp -r nginx arbore@192.168.163.134:/home/arbore/console/
```

### 2. 在服务器上构建和启动

SSH连接到服务器后执行：

```bash
# 进入项目目录
cd /home/arbore/console

# 构建Web管理界面服务
docker compose build web-admin-api web-admin-frontend

# 启动服务
docker compose up -d web-admin-api web-admin-frontend nginx

# 查看服务状态
docker compose ps | grep -E "web-admin|nginx"

# 查看日志
docker compose logs -f web-admin-api
```

### 3. 验证访问

在浏览器中访问：
- Web管理界面：`http://192.168.163.134:9000`
- 或通过Nginx：`http://192.168.163.134:80`

## 🔧 故障排查

### 如果构建失败

```bash
# 查看详细构建日志
docker compose build --no-cache web-admin-api
docker compose build --no-cache web-admin-frontend
```

### 如果服务无法启动

```bash
# 查看容器日志
docker logs arbore-web-admin-api
docker logs arbore-web-admin-frontend
docker logs arbore-nginx

# 检查端口占用
netstat -tuln | grep -E "8002|9000|80"
```

### 如果API无法访问

```bash
# 测试API连接
curl http://localhost:8002/
curl http://localhost:8002/api/v1/services

# 检查Docker socket权限
ls -la /var/run/docker.sock
```

## 📝 注意事项

1. **Docker Socket权限**：web-admin-api需要访问Docker socket来监控容器状态
2. **网络连接**：确保所有服务在同一Docker网络中（arbore-network）
3. **端口冲突**：确保端口80、8002、9000未被占用

## 🔄 远程更新（OTA）

- **默认**：遥测/更新检查为开启，无需配置。
- **关闭**：设置环境变量 `ARBORE_OTA_DISABLED=1`（或 `true`/`yes`），则不再检查远程版本，且无法通过界面执行「立即更新」。

示例（systemd 服务中关闭）：

```ini
Environment="ARBORE_OTA_DISABLED=1"
```

## ⚠️ 自定义服务 404

若「自定义服务」列表或添加服务时报 404：

1. 确认 Nginx 已将 `/admin-api/` 和 `/api/` 反向代理到后端 8002（参见 `deploy/web-admin.conf`）。
2. 确认部署的是**最新**后端（含 `custom-services` 相关路由）和前端（请求路径为 `/admin-api/api/v1/custom-services`）。
3. 重新构建并上传前端后，强刷页面（Ctrl+F5）或清缓存后再试。

