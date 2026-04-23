# 構建方法（WSL 下執行）

## 一、本地構建與運行

### 1. 增量同步到 n8n-build（不刪目錄，只更新有變動的文件，第二次起很快）
```bash
cd ~
mkdir -p ~/n8n-build
rsync -ah --progress \
  --exclude 'node_modules' \
  --exclude '.git' \
  --exclude 'proc' \
  --exclude '*.tar.gz' \
  --exclude '.turbo' \
  --exclude 'packages/*/node_modules' \
  --exclude 'packages/*/.turbo' \
  /mnt/c/n8n-workspace/n8n/ ~/n8n-build/
```

### 2. 安裝依賴並打包（會先 build，再生成 proc）
```bash
cd ~/n8n-build
pnpm install
pnpm package:prod
```

### 3. 打鏡像（構建產物已在 proc 內，鏡像內只安裝依賴）
```bash
cd ~/n8n-build/proc
sudo docker build --no-cache -t arbore-prod:001.0063 .
```

### 4. 本機起容器
```bash
sudo docker stop arbore-flow 2>/dev/null
sudo docker rm arbore-flow 2>/dev/null
sudo docker run -d \
  --name arbore-flow \
  -p 5678:5678 \
  -v /home/arbore/n8n-build/proc/data:/app/data \
  -v /home/arbore/n8n-build/proc/custom-nodes:/app/custom-nodes \
  -v /home/arbore/n8n-build/proc/license.json:/app/license.json \
  --restart unless-stopped \
  --entrypoint "" \
  -e N8N_DEFAULT_LOCALE=en \
  arbore-prod:001.0063 \
  /bin/sh /app/start-prod.sh
```

### 5. 看日誌
```bash
sudo docker logs -f arbore-flow
```

---

## 二、導出 tar 並部署到服務器

### 6. 導出鏡像為 tar（在構建機執行）
```bash
cd ~/n8n-build/proc
sudo docker save -o arbore-prod.tar arbore-prod:001.0063
# 可選：壓縮以減小傳輸體積
# gzip -k -f arbore-prod.tar
# 得到 arbore-prod.tar.gz
```

### 7. 拷貝到 n8n 目錄（再從本機傳到服務器或拷盤）
```bash
sudo cp ~/n8n-build/proc/arbore-prod.tar /mnt/c/n8n-workspace/n8n/
# 或只導出未壓縮的 tar：
# cp ~/n8n-build/proc/arbore-prod.tar /mnt/c/n8n-workspace/n8n/
```

### 8. 在服務器上加載並運行（目錄鎖定為 /home/arbore/console/）
```bash
cd /home/arbore/console

# 加載鏡像
# 若為 .tar：docker load -i arbore-prod.tar
# 若為 .tar.gz：gunzip -c arbore-prod.tar.gz | docker load
docker load -i arbore-prod.tar

# 創建數據目錄與許可證占位（首次部署；若已有 data/custom-nodes 可跳過）
mkdir -p /home/arbore/console/data /home/arbore/console/custom-nodes
touch /home/arbore/console/license.json

# 啟動容器（鏡像名與標籤需與導出時一致）
docker stop arbore-flow 2>/dev/null
docker rm arbore-flow 2>/dev/null
docker run -d \
  --name arbore-flow \
  -p 5678:5678 \
  -v /home/arbore/console/data:/app/data \
  -v /home/arbore/console/custom-nodes:/app/custom-nodes \
  -v /home/arbore/console/license.json:/app/license.json \
  --restart unless-stopped \
  --entrypoint "" \
  -e N8N_DEFAULT_LOCALE=en \
  -e N8N_DATABASE_SQLITE_DATABASE=/app/data/arbore-flow/database.sqlite \
  -e N8N_DB_SQLITE_DATABASE=/app/data/arbore-flow/database.sqlite \
  arbore-prod:001.0063 \
  /bin/sh /app/start-prod.sh

# 看日誌
docker logs -f arbore-flow
```

**說明**：上面已加上 `-e` 指向舊庫；若鏡像仍是舊版 start-prod.sh，`-e` 可能不生效。此時用下面「恢復舊庫」即可。

---

## 三、沒連上舊庫時：在服務器上直接恢復（不改鏡像、不重傳）

當前鏡像默認讀的是 `data/database.sqlite`。把舊庫拷到該路徑後重啟即可：

```bash
cd /home/arbore/console

# 1. 停容器
docker stop arbore-flow
docker rm arbore-flow

# 2. n8n 實際會讀 N8N_USER_FOLDER/.n8n/database.sqlite，所以要把舊庫放進 .n8n
mkdir -p data/.n8n
cp -a data/arbore-flow/database.sqlite data/.n8n/database.sqlite
# 再拷一份到根目錄（部分鏡像用 N8N_DATABASE_SQLITE_DATABASE=/app/data/database.sqlite）
cp -a data/arbore-flow/database.sqlite data/database.sqlite

# 3. 確認文件大小（舊庫一般幾 MB，若只有幾十 KB 說明拷錯或損壞）
ls -la data/arbore-flow/database.sqlite data/.n8n/database.sqlite data/database.sqlite

# 4. 按步驟 8 的 docker run 再起一次（可去掉兩行 -e）
docker run -d \
  --name arbore-flow \
  -p 5678:5678 \
  -v /home/arbore/console/data:/app/data \
  -v /home/arbore/console/custom-nodes:/app/custom-nodes \
  -v /home/arbore/console/license.json:/app/license.json \
  --restart unless-stopped \
  --entrypoint "" \
  -e N8N_DEFAULT_LOCALE=en \
  arbore-prod:001.0063 \
  /bin/sh /app/start-prod.sh

docker logs -f arbore-flow
```

完成後訪問 `http://服務器IP:5678`，應為登錄頁而非「Set up owner account」。

訪問：`http://服務器IP:5678`