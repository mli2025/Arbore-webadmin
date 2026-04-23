# Web Admin Linux系统部署说明

## 📋 概述

Web管理界面改为在Linux系统上直接运行，而不是Docker容器。这样：
- ✅ 访问Docker socket更简单（直接访问，无需挂载）
- ✅ 更新代码更直接（修改文件后重启服务即可）
- ✅ 不需要每次更新都重新构建镜像
- ✅ 更符合"管理工具"的定位

## 🚀 部署步骤

### 1. 确保用户权限

```bash
# 将arbore用户添加到docker组（如果还没有）
sudo usermod -aG docker arbore

# 重新登录或执行以下命令使组权限生效
newgrp docker

# 验证Docker访问权限
docker ps
```

### 2. 安装Python依赖

```bash
cd /home/arbore/console/web-admin/backend

# 安装Python依赖（使用--user安装到用户目录）
pip3 install --user -r requirements.txt

# 如果uvicorn未安装
pip3 install --user uvicorn[standard]
```

### 3. 配置systemd服务

```bash
cd /home/arbore/console

# 复制systemd服务文件
sudo cp systemd/arbore-web-admin-api.service /etc/systemd/system/

# 重新加载systemd配置
sudo systemctl daemon-reload

# 启用服务（开机自启）
sudo systemctl enable arbore-web-admin-api.service

# 启动服务
sudo systemctl start arbore-web-admin-api.service

# 检查服务状态
sudo systemctl status arbore-web-admin-api.service
```

### 4. 停止Docker容器（如果存在）

```bash
cd /home/arbore/console

# 停止并删除web-admin-api容器
docker compose stop web-admin-api
docker compose rm -f web-admin-api

# 可选：从docker-compose.yml中注释掉web-admin-api服务
```

### 5. 验证部署

```bash
# 测试API
curl http://localhost:8002/
curl http://localhost:8002/api/v1/version

# 查看日志
sudo journalctl -u arbore-web-admin-api.service -f
```

## 🔧 服务管理

### 启动/停止/重启

```bash
# 启动服务
sudo systemctl start arbore-web-admin-api

# 停止服务
sudo systemctl stop arbore-web-admin-api

# 重启服务
sudo systemctl restart arbore-web-admin-api

# 查看状态
sudo systemctl status arbore-web-admin-api
```

### 查看日志

```bash
# 实时日志
sudo journalctl -u arbore-web-admin-api.service -f

# 最近50行日志
sudo journalctl -u arbore-web-admin-api.service -n 50

# 查看错误日志
sudo journalctl -u arbore-web-admin-api.service -p err
```

## 📝 更新代码

更新代码后，只需重启服务即可：

```bash
# 方法1: 直接重启
sudo systemctl restart arbore-web-admin-api

# 方法2: 使用更新脚本
cd /home/arbore/console
chmod +x web-admin/更新代码并重启.sh
./web-admin/更新代码并重启.sh
```

## 🌐 前端部署

前端可以继续使用Docker容器（Nginx），或者使用系统Nginx：

### 选项1: 继续使用Docker容器（推荐）

前端容器保持不变，只需更新nginx配置中的API地址：

```nginx
# nginx/conf.d/default.conf
location /api {
    proxy_pass http://localhost:8002;  # 改为localhost，因为API在宿主机上
    ...
}
```

### 选项2: 使用系统Nginx

```bash
# 安装Nginx
sudo apt-get install nginx

# 配置Nginx（参考nginx/conf.d/default.conf）
# 将前端构建产物复制到 /var/www/html/web-admin
# 配置反向代理到 http://localhost:8002
```

## ✅ 验证清单

- [ ] Python3已安装
- [ ] Python依赖已安装
- [ ] arbore用户在docker组中
- [ ] systemd服务已配置并启动
- [ ] API可以访问：`curl http://localhost:8002/api/v1/version`
- [ ] Docker客户端可以访问（检查日志中是否有"Docker client initialized"）

## 🔍 故障排查

### 如果服务无法启动

```bash
# 查看详细错误
sudo journalctl -u arbore-web-admin-api.service -n 50

# 检查Python路径
which python3
python3 --version

# 检查依赖是否安装
python3 -c "import fastapi, uvicorn; print('OK')"
```

### 如果Docker客户端无法访问

```bash
# 检查用户是否在docker组
groups arbore

# 检查Docker socket权限
ls -l /var/run/docker.sock

# 测试Docker访问
docker ps
```

### 如果端口被占用

```bash
# 检查端口占用
sudo netstat -tlnp | grep 8002

# 或使用
sudo lsof -i :8002
```

