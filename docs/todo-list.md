## Web-Admin 多档许可证分级 + 标准服务管理 TODO

### 阶段 1：许可证分级改造

- [ ] 扩展 `license.json` 结构，增加 `features` 字段（`standard_services` / `custom_services` / `rpa`），设计默认策略与签发规则。
- [ ] 更新 `license_utils.py`：在 `validate_license()` 返回中增加 `features`，提供 `check_feature(feature_name)` 辅助函数。
- [ ] 更新 `validation-code-generator.js`：支持 `features` 参数，生成包含能力信息的许可证（先与后端保持同一签名逻辑方案）。
- [ ] 设计后端使用方式：标准服务、自定义服务、RPA 在关键 API 中统一通过 `check_feature()` 校验。
- [ ] 设计前端展示逻辑：`ServicesView`、`CustomServicesView`、`LicenseView` 按 `features` 控制按钮启用与能力标签展示。

### 阶段 2：标准服务管理（安装 / 删除 / 修复 / 更新）

- [ ] 定义标准服务清单结构（本地 `backend/standard_services.json` 或远程接口）：包含 `id`、`name`、`description`、`image`、`version`、`category`、`removable`、`compose_template`。
- [ ] 设计/实现后端标准服务 API：
  - [ ] `GET /api/v1/standard-services`：清单 + 容器状态合并，标注“已安装 / 未安装 / 可更新”。
  - [ ] `POST /api/v1/standard-services/{id}/install`：将模板写入 `docker-compose.yml`，并约定运维执行 `docker compose up -d`。
  - [ ] `DELETE /api/v1/standard-services/{id}`：仅在 `removable: true` 时允许，从 compose 和容器中彻底移除。
  - [ ] `POST /api/v1/standard-services/{id}/repair`：同版本强制重建容器。
  - [ ] `POST /api/v1/standard-services/{id}/update`：更新 image/tag 并重启服务。
- [ ] 在标准服务 API 中统一校验 `features.standard_services`。
- [ ] 前端 `ServicesView`：改为从 `/api/v1/standard-services` 获取数据，按“安装 / 修复 / 删除 / 更新”按钮组合展示。

### 阶段 3：自定义服务管理改善

- [ ] 确认 `parse_docker_compose_custom_services()` 的策略：**始终**合并 Docker 容器与 `docker-compose.yml`，保证只要 compose 中存在定义，就能在列表中显示（即使容器未运行）。
- [ ] 校验服务器部署版本，确保刷新页面不会导致自定义服务列表丢失。
- [ ] 梳理自定义服务删除流程：容器已停/不存在时不报错，依然清理 compose 与本地元数据。
- [ ] 保持“服务详情”中的容器日志查看能力，作为排查起不来的服务的主要入口。

### 阶段 4：升级与运维流程（文档层面）

- [ ] 定义 web-admin 主程序升级推荐流程：以“重新部署镜像 + 更新 `docker-compose.yml` + `docker compose up -d`”为主，web-admin 内部仅做版本检测与提醒。
- [ ] 为标准服务（flow/func/quickchart/OCR 等）编写升级/回滚手册，基于阶段 2 的 API 与清单。
- [ ] 设计（可选）自定义服务备份与迁移方案：导出配置 JSON + 镜像 tar，定义导入/选装流程。

