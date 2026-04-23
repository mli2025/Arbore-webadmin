# Arbore WebAdmin 离线部署步骤（新服务器）

适用场景：
- 服务器是全新 Ubuntu 24.04 LTS
- 可能只能用 `root` 登录
- 服务器在内网，无法访问 GitHub
- 目标先跑通：`Portainer + web-admin-api + web-admin-frontend`

---

## 1. 先决策：是否创建 `arbore` 用户

推荐：**创建 `arbore` 用户**，后续部署和运维都更稳定。  
不推荐长期用 `root` 直接跑应用。

如果当前是 `root`，先执行：

```bash
adduser arbore
```

```bash
usermod -aG sudo arbore
```

> Docker 安装后再执行一次 `usermod -aG docker arbore`。

切换用户：

```bash
su - arbore
```

---

## 2. 安装 Docker 与 Docker Compose V2（服务器执行）

如果你在 `root` 下执行，命令直接可用；若在普通用户下，请在前面加 `sudo`。

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release unzip
```

```bash
install -m 0755 -d /etc/apt/keyrings
```

```bash
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
```

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
```

```bash
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker
systemctl start docker
```

如果已创建 `arbore` 用户，补充执行：

```bash
usermod -aG docker arbore
```

---

## 3. 内网离线准备（在有外网的本地机器执行）

以下步骤在你本地 Windows 执行（不是服务器）。

### 3.1 准备代码包

将 `Arbore-webadmin` 目录打包为 zip：

```powershell
Compress-Archive -Path C:\temp\Arbore-webadmin\* -DestinationPath C:\temp\Arbore-webadmin-offline.zip -Force
```

### 3.2 准备镜像包

```powershell
cd C:\temp\Arbore-webadmin
docker pull portainer/portainer-ce:2.21.5
docker build -t arbore-web-admin-api:offline -f backend\Dockerfile backend
docker build -t arbore-web-admin-frontend:offline -f frontend\Dockerfile frontend
docker save -o C:\temp\arbore-images-offline.tar portainer/portainer-ce:2.21.5 arbore-web-admin-api:offline arbore-web-admin-frontend:offline
```

最终你需要把这两个文件传到服务器：
- `Arbore-webadmin-offline.zip`
- `arbore-images-offline.tar`

---

## 4. 服务器落地代码与镜像（服务器执行）

假设文件已经传到 `/home/arbore/console/`。

```bash
mkdir -p /home/arbore/console
cd /home/arbore/console
```

```bash
mkdir -p /home/arbore/console/Arbore-webadmin
unzip -o /home/arbore/console/Arbore-webadmin-offline.zip -d /home/arbore/console/Arbore-webadmin
```

```bash
docker load -i /home/arbore/console/arbore-images-offline.tar
```

---

## 5. 写最小可运行 `docker-compose.yml`（服务器执行）

文件路径：
- `/home/arbore/console/Arbore-webadmin/docker-compose.yml`

内容如下（完整替换）：

```yaml
services:
  portainer:
    image: portainer/portainer-ce:2.21.5
    container_name: portainer
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - portainer_data:/data
    ports:
      - "9001:9000"
    networks:
      - arbore-network

  web-admin-api:
    image: arbore-web-admin-api:offline
    container_name: arbore-web-admin-api
    restart: unless-stopped
    env_file:
      - ./.env
    volumes:
      - ./runtime-data:/app-data
    expose:
      - "8002"
    depends_on:
      - portainer
    networks:
      - arbore-network

  web-admin-frontend:
    image: arbore-web-admin-frontend:offline
    container_name: arbore-web-admin-frontend
    restart: unless-stopped
    ports:
      - "9000:80"
    depends_on:
      - web-admin-api
    networks:
      - arbore-network

networks:
  arbore-network:
    name: arbore-network
    driver: bridge

volumes:
  portainer_data:
```

---

## 6. 启动 Portainer 并创建 API Key（服务器 + 浏览器）

先仅启动 Portainer：

```bash
cd /home/arbore/console/Arbore-webadmin
docker compose up -d portainer
```

浏览器访问：
- `http://<服务器IP>:9001`

在 Portainer 完成：
1. 初始化管理员账户
2. 进入本地 Docker 环境
3. `My account -> API keys -> Add API key`
4. 复制生成的 API Key

---

## 7. 写 `.env`（服务器执行）

文件路径：
- `/home/arbore/console/Arbore-webadmin/.env`

内容模板：

```env
PORTAINER_URL=http://portainer:9000
PORTAINER_API_KEY=替换为你的真实key
PORTAINER_ENDPOINT_ID=1
PORTAINER_VERIFY_SSL=false
PORTAINER_TIMEOUT=60
ARBORE_NETWORK_NAME=arbore-network
ARBORE_RESTART_POLICY=unless-stopped
ARBORE_PROJECT_ROOT=/app-data
```

---

## 8. 启动 WebAdmin（服务器执行）

```bash
cd /home/arbore/console/Arbore-webadmin
mkdir -p /home/arbore/console/Arbore-webadmin/runtime-data/config/custom-services
docker compose up -d web-admin-api web-admin-frontend
```

查看后端日志：

```bash
cd /home/arbore/console/Arbore-webadmin
docker compose logs -f web-admin-api
```

---

## 9. 验证

访问前端：
- `http://<服务器IP>:9000`

检查后端版本接口：
- `http://<服务器IP>:9000/admin-api/api/v1/version`

期望字段：
- `portainer_configured: true`
- `portainer_reachable: true`

---

## 10. 常见问题快速定位

1. `portainer_reachable=false`
   - 检查 `.env` 的 `PORTAINER_API_KEY` 是否正确
   - 检查 `PORTAINER_ENDPOINT_ID`（默认一般是 1）

2. 前端打不开
   - 检查 `docker compose ps`
   - 检查端口 `9000` 是否被占用

3. 上传 tar 失败
   - 先看 `web-admin-api` 日志
   - 确认磁盘空间足够

4. 权限问题
   - 建议固定用 `arbore` 用户操作
   - 确认 `/home/arbore/console/Arbore-webadmin` 目录归属为 `arbore:arbore`

---

按上面 1-9 步执行即可完成首轮上线。  
等你跑完第一轮，我再给你“第二阶段（加回 n8n/nocobase）”的最小增量步骤。

