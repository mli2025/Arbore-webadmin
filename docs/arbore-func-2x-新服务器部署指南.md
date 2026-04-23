# arbore-func 2.x 新服务器部署指南（端口 13001）

本文档用于在**新服务器**上部署 arbore-func 2.x，对外端口 **13001**。包含：创建数据库、上传镜像 tar、启动 Docker。

---

## 一、前置条件

- 服务器已安装 Docker、Docker Compose（V2）
- 已准备好 arbore-func 2.x 的镜像 tar 包（如 `arbore-func-2x.tar` 或 `nocobase-beta-full.tar`）
- 规划好部署目录，例如：`/home/arbore/arbore-func-v2` 或 `/opt/arbore-func-2x`

---

## 二、创建部署目录

在服务器上执行（路径可按实际修改）：

```bash
mkdir -p /home/arbore/arbore-func-v2
cd /home/arbore/arbore-func-v2
```

---

## 三、创建数据库

### 方式 A：使用 Docker 单独起一个 PostgreSQL（推荐，与现有 13000 环境隔离）

1. 创建数据目录并启动临时 PostgreSQL（仅用于建库）：

```bash
mkdir -p /home/arbore/arbore-func-v2/data/postgres-2x
docker run -d --name postgres-2x-temp \
  -e POSTGRES_USER=arbore \
  -e POSTGRES_PASSWORD=arbore \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v /home/arbore/arbore-func-v2/data/postgres-2x:/var/lib/postgresql/data \
  -p 5434:5432 \
  postgres:16
```

2. 等待数据库就绪后创建业务库：

```bash
sleep 5
docker exec -it postgres-2x-temp psql -U arbore -d postgres -c "CREATE DATABASE nocobase2x;"
```

3. 停止并删除临时容器，改用 compose 中的 postgres 服务时可跳过；若本方案为独立 Postgres，可将上面 `docker run` 改为 `restart: unless-stopped` 长期运行，并记下：**主机 5434、库名 nocobase2x、用户 arbore、密码 arbore**。

### 方式 B：在已有 PostgreSQL 上创建新库

若服务器上已有 PostgreSQL（如 5432 端口），可直接建库：

```bash
# 示例：本机已有 postgres 容器，名为 arbore-postgres
docker exec -it arbore-postgres psql -U arbore -d postgres -c "CREATE DATABASE nocobase2x;"
```

或使用 `psql` 客户端：

```bash
psql -h <DB_HOST> -p 5432 -U arbore -d postgres -c "CREATE DATABASE nocobase2x;"
```

记下：**DB_HOST、端口、库名 nocobase2x、用户、密码**，供下文环境变量使用。

---

## 四、上传镜像 tar 并加载

1. 将本地的 arbore-func 2.x 镜像 tar 上传到服务器部署目录，例如：

```bash
# 在本地执行（示例，请替换为实际 tar 路径与服务器 IP）
scp /path/to/arbore-func-2x.tar arbore@<服务器IP>:/home/arbore/arbore-func-v2/
```

2. 在服务器上加载镜像：

```bash
cd /home/arbore/arbore-func-v2
docker load -i arbore-func-2x.tar
```

3. 查看镜像名与版本（用于下文 `image`）：

```bash
docker images | grep -E "nocobase|arbore-func"
```

记下镜像名，例如：`nocobase/nocobase:beta-full` 或 `arbore-func-2x:latest`。

---

## 五、准备配置文件与存储目录

1. 创建 arbore-func 存储目录：

```bash
mkdir -p /home/arbore/arbore-func-v2/data/arbore-func-2x/storage
```

2. 创建环境变量文件（按实际数据库信息修改）：

```bash
cat > /home/arbore/arbore-func-v2/.env << 'EOF'
# 数据库（与第三节创建的库一致）
POSTGRES_NOCOBASE_DB=nocobase2x
POSTGRES_NOCOBASE_USER=arbore
POSTGRES_NOCOBASE_PASSWORD=arbore

# arbore-func 应用
ARBORE_FUNC_APP_KEY=arbore-secret-key-2024
ARBORE_FUNC_ENCRYPTION_KEY=arbore-secret-key-2024
EOF
```

3. 若使用方式 A 的独立 Postgres（本机 5434），需在 compose 中把 DB 端口改为 5434，或先启动该 Postgres 再启动 arbore-func。

---

## 六、编写 docker-compose（端口 13001）

在部署目录创建 `docker-compose.yml`：

```yaml
services:
  postgres-2x:
    image: postgres:16
    container_name: arbore-postgres-2x
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_NOCOBASE_DB:-nocobase2x}
      POSTGRES_USER: ${POSTGRES_NOCOBASE_USER:-arbore}
      POSTGRES_PASSWORD: ${POSTGRES_NOCOBASE_PASSWORD:-arbore}
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - ./data/postgres-2x:/var/lib/postgresql/data
    networks:
      - arbore-2x
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_NOCOBASE_USER:-arbore}"]
      interval: 10s
      timeout: 5s
      retries: 5

  arbore-func-2x:
    image: nocobase/nocobase:beta-full
    container_name: arbore-func-2x
    restart: unless-stopped
    environment:
      APP_KEY: ${ARBORE_FUNC_APP_KEY:-arbore-secret-key-2024}
      ENCRYPTION_FIELD_KEY: ${ARBORE_FUNC_ENCRYPTION_KEY:-arbore-secret-key-2024}
      DB_DIALECT: postgres
      DB_HOST: postgres-2x
      DB_PORT: 5432
      DB_DATABASE: ${POSTGRES_NOCOBASE_DB:-nocobase2x}
      DB_USER: ${POSTGRES_NOCOBASE_USER:-arbore}
      DB_PASSWORD: ${POSTGRES_NOCOBASE_PASSWORD:-arbore}
      TZ: Asia/Shanghai
    volumes:
      - ./data/arbore-func-2x/storage:/app/nocobase/storage
    ports:
      - "13001:80"
    networks:
      - arbore-2x
    depends_on:
      postgres-2x:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:80/ || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 90s

networks:
  arbore-2x:
    driver: bridge
```

若使用**自己上传的 tar 镜像**，将 `arbore-func-2x` 的 `image` 改为加载后看到的镜像名，例如：

```yaml
    image: arbore-func-2x:latest
```

---

## 七、启动服务

```bash
cd /home/arbore/arbore-func-v2
docker compose up -d
```

查看状态与日志：

```bash
docker compose ps
docker compose logs -f arbore-func-2x
```

---

## 八、验证访问

- 浏览器访问：`http://<服务器IP>:13001`
- 首次访问按提示创建超级管理员账号并完成初始化

---

## 九、常用命令速查

| 操作       | 命令 |
|------------|------|
| 启动       | `cd /home/arbore/arbore-func-v2 && docker compose up -d` |
| 停止       | `docker compose stop` |
| 重启       | `docker compose restart` |
| 查看日志   | `docker compose logs -f arbore-func-2x` |
| 进入容器   | `docker compose exec arbore-func-2x sh` |

---

## 十、若第三节已手动建库（方式 B）

可只启动 arbore-func 容器，不启动 compose 里的 postgres-2x，并修改环境变量：

- `DB_HOST`：改为现有 PostgreSQL 的 host（容器名或 IP）
- `DB_PORT`：一般为 5432
- `DB_DATABASE`：`nocobase2x`
- `DB_USER` / `DB_PASSWORD`：与现有库一致

此时 `docker-compose.yml` 中可删除 `postgres-2x` 服务，并去掉 `depends_on`，仅保留 `arbore-func-2x` 与 `ports: "13001:80"`。

---

实际部署时请将示例路径、镜像名、数据库密码等替换为当前环境配置。
