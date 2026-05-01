<template>
  <!--
    服务状态视图 / Services View

    中文说明：
    本组件负责集中展示 Arbore AI Host 平台中各个核心服务（Docker 容器或 systemd
    服务）的运行状态、健康检查结果以及常用操作入口。每张卡片对应一项标准服务，
    其展示元数据（显示名、描述、图标、宿主机端口）从后端
    /api/v1/standard-services/config 加载，并可通过右上角齿轮图标进行配置。

    English description:
    This view aggregates the runtime state of all core services that make up
    the Arbore AI Host platform.  Each card represents one standard service.
    Card metadata (display name, description, icon, host port) is loaded from
    the backend's /api/v1/standard-services/config endpoint and is editable
    in‑place via the gear button at the top right of the page.

    设计关注点 / Design considerations:
    - 配置即视图：管理员通过右上角齿轮即可增删改标准服务卡片，不动任何容器；
    - 状态合并：未在后端返回中匹配到的 key 仍渲染一张「未找到」卡片，便于占位；
    - 暗色主题：整体配色与 Arbore 品牌一致，强化卡片层次与状态语义色。
  -->
  <div class="services-view">
    <el-alert
      v-if="!licenseValid && licenseErrorCode"
      type="warning"
      :closable="false"
      show-icon
      class="license-alert"
    >
      <template #title>
        未注册或许可证无效，标准服务无法启动/重启。请前往「许可证」页完成注册。
      </template>
    </el-alert>

    <!-- 顶部工具条：标题 + 操作按钮 -->
    <div class="toolbar">
      <div class="toolbar-title">
        <span class="dot" />
        标准服务
        <span class="count">{{ cards.length }}</span>
      </div>
      <div class="toolbar-actions">
        <el-button
          :icon="RefreshRight"
          :loading="loading"
          @click="refreshAll"
        >
          刷新状态
        </el-button>
        <el-tooltip content="管理标准服务" placement="bottom">
          <el-button
            :icon="Setting"
            circle
            class="gear-btn"
            @click="openConfigDialog"
          />
        </el-tooltip>
      </div>
    </div>

    <el-empty v-if="cards.length === 0" description="尚未配置任何标准服务，点击右上角齿轮添加" />

    <el-row :gutter="20" v-else>
      <el-col :span="8" v-for="card in cards" :key="card.key">
        <el-card class="service-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <component
                  :is="resolveIcon(card.icon)"
                  class="card-icon"
                />
                <span class="service-name">{{ card.display || card.key }}</span>
              </div>
              <el-tag :type="getStatusType(card.status)" size="small" effect="dark">
                {{ getStatusText(card.status) }}
              </el-tag>
            </div>
          </template>

          <div class="service-info">
            <p v-if="card.description" class="service-desc">
              {{ card.description }}
            </p>
            <p class="meta-row">
              <span class="meta-label">容器</span>
              <code class="meta-code">{{ card.key }}</code>
            </p>
            <p v-if="card.health && card.health !== 'unknown'" class="meta-row">
              <span class="meta-label">健康</span>
              <el-tag :type="card.health === 'healthy' ? 'success' : 'warning'" size="small">
                {{ card.health }}
              </el-tag>
            </p>
            <p v-if="card.ports && card.ports.length > 0" class="meta-row">
              <span class="meta-label">端口</span>
              <span class="meta-value">{{ card.ports.join(', ') }}</span>
            </p>
            <p v-if="card.type === 'systemd'" class="meta-row">
              <span class="meta-label">类型</span>
              <el-tag size="small" type="info">Systemd</el-tag>
            </p>

            <div class="service-actions">
              <el-button
                type="primary"
                size="small"
                :icon="Link"
                @click="openService(card)"
                :disabled="card.status !== 'running' || !card.port"
              >
                访问服务
              </el-button>

              <el-button
                v-if="card.status !== 'running' && card.canControl"
                type="success"
                size="small"
                :icon="VideoPlay"
                @click="startService(card)"
                :loading="card.loading"
                :disabled="!licenseValid"
              >
                启动
              </el-button>

              <el-button
                v-if="card.status === 'running' && card.canControl"
                type="warning"
                size="small"
                :icon="VideoPause"
                @click="stopService(card)"
                :loading="card.loading"
              >
                停止
              </el-button>

              <el-button
                v-if="card.status === 'running' && card.canControl"
                type="info"
                size="small"
                :icon="Refresh"
                @click="restartService(card)"
                :loading="card.loading"
                :disabled="!licenseValid"
              >
                重启
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 配置弹窗 -->
    <el-dialog
      v-model="configVisible"
      title="管理标准服务"
      width="900px"
      :close-on-click-modal="false"
      class="services-config-dialog"
    >
      <div class="config-tip">
        在此维护"服务状态"页要展示的标准服务卡片。仅修改展示元数据（容器名、显示名、描述、图标、宿主机端口），不会创建/删除任何容器。
      </div>

      <el-table
        :data="configDraft"
        border
        size="small"
        class="config-table"
        empty-text="暂无服务，点击下方「添加服务」按钮新增"
      >
        <el-table-column label="容器名 (key)" min-width="180">
          <template #default="{ row }">
            <el-input
              v-model="row.key"
              placeholder="例如 arbore-flow"
              size="small"
              spellcheck="false"
            />
          </template>
        </el-table-column>

        <el-table-column label="显示名" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.display" placeholder="例如 工作流服务" size="small" />
          </template>
        </el-table-column>

        <el-table-column label="描述" min-width="200">
          <template #default="{ row }">
            <el-input v-model="row.description" placeholder="一句话描述（选填）" size="small" />
          </template>
        </el-table-column>

        <el-table-column label="图标" width="180">
          <template #default="{ row }">
            <el-select v-model="row.icon" size="small" placeholder="选择图标">
              <el-option
                v-for="opt in iconOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              >
                <span class="icon-option">
                  <component :is="opt.value" class="icon-option-svg" />
                  <span>{{ opt.label }}</span>
                </span>
              </el-option>
            </el-select>
          </template>
        </el-table-column>

        <el-table-column label="宿主机端口" width="130">
          <template #default="{ row }">
            <el-input-number
              v-model="row.port"
              :min="0"
              :max="65535"
              :step="1"
              :controls="false"
              size="small"
              placeholder="0"
              style="width: 100%;"
            />
          </template>
        </el-table-column>

        <el-table-column label="操作" width="80" align="center">
          <template #default="{ $index }">
            <el-button
              type="danger"
              size="small"
              :icon="Delete"
              circle
              plain
              @click="removeRow($index)"
            />
          </template>
        </el-table-column>
      </el-table>

      <div class="config-add">
        <el-button :icon="Plus" plain @click="addRow">添加服务</el-button>
        <span class="config-hint">端口为 0 表示无 Web 访问入口（如纯数据库）</span>
      </div>

      <template #footer>
        <el-button @click="configVisible = false" :disabled="configSaving">取消</el-button>
        <el-button type="primary" :loading="configSaving" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount, markRaw } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  RefreshRight,
  Setting,
  Refresh,
  VideoPlay,
  VideoPause,
  Link,
  Plus,
  Delete,
  Connection,
  Grid,
  Coin,
  DataLine,
  Cpu,
  ChatDotRound,
  Monitor,
  Service,
  Box,
  Promotion,
  Tools,
  Files,
  Help,
  DataAnalysis,
} from '@element-plus/icons-vue'

// ----------------------------------------------------------------------------
// 状态 / Reactive state
// ----------------------------------------------------------------------------
const services = ref([])           // 后端 /api/v1/services 返回的容器状态
const configItems = ref([])        // 后端 /api/v1/standard-services/config 返回的展示配置
const loading = ref(false)
const licenseValid = ref(true)
const licenseErrorCode = ref(null)

const configVisible = ref(false)
const configSaving = ref(false)
const configDraft = ref([])        // 弹窗中的可编辑副本

// 图标候选：仅暴露这一组常用图标，避免用户输入未注册的图标名
// 使用 markRaw 让 :is 直接拿到组件引用，不会触发响应式追踪带来的告警
const ICONS = {
  Connection: markRaw(Connection),
  Grid: markRaw(Grid),
  Coin: markRaw(Coin),
  DataLine: markRaw(DataLine),
  Cpu: markRaw(Cpu),
  ChatDotRound: markRaw(ChatDotRound),
  Monitor: markRaw(Monitor),
  Service: markRaw(Service),
  Box: markRaw(Box),
  Promotion: markRaw(Promotion),
  Tools: markRaw(Tools),
  Files: markRaw(Files),
  Help: markRaw(Help),
  DataAnalysis: markRaw(DataAnalysis),
}

const iconOptions = [
  { value: 'Connection', label: '工作流' },
  { value: 'Grid', label: '应用' },
  { value: 'Coin', label: '数据库' },
  { value: 'DataLine', label: '向量库' },
  { value: 'Cpu', label: 'AI 模型' },
  { value: 'ChatDotRound', label: 'AI 对话' },
  { value: 'Monitor', label: '看板/前端' },
  { value: 'Service', label: '后端服务' },
  { value: 'Box', label: '容器/包' },
  { value: 'Promotion', label: '消息/推送' },
  { value: 'Tools', label: '工具' },
  { value: 'Files', label: '文件' },
  { value: 'DataAnalysis', label: '分析' },
  { value: 'Help', label: '其他' },
]

const resolveIcon = (name) => ICONS[name] || ICONS.Help

// ----------------------------------------------------------------------------
// 派生：合并配置 + 后端状态生成卡片
// ----------------------------------------------------------------------------
const cards = computed(() => {
  const stateMap = new Map()
  for (const s of services.value) stateMap.set(s.name, s)
  return configItems.value.map((cfg) => {
    const s = stateMap.get(cfg.key) || {
      name: cfg.key, status: 'not_found', health: 'unknown', ports: [], type: 'docker',
    }
    const canControl = s.type === 'systemd' || cfg.key.startsWith('service-')
    return {
      ...cfg,
      status: s.status,
      health: s.health,
      ports: s.ports || [],
      type: s.type || 'docker',
      canControl,
      loading: false,
    }
  })
})

// ----------------------------------------------------------------------------
// 工具
// ----------------------------------------------------------------------------
const getServerIP = () => window.location.hostname
const getBaseUrl = () => `${window.location.protocol}//${getServerIP()}`

const getStatusType = (status) => ({
  running: 'success', stopped: 'danger', exited: 'danger',
  restarting: 'warning', not_found: 'info', unknown: 'info',
}[status] || 'info')

const getStatusText = (status) => ({
  running: '运行中', stopped: '已停止', exited: '已停止',
  restarting: '重启中', not_found: '未找到', unknown: '未知',
}[status] || status)

const openService = (card) => {
  if (!card.port) {
    ElMessage.info('该服务没有 Web 访问地址')
    return
  }
  const url = `${getBaseUrl()}:${card.port}`
  try {
    window.open(url, '_blank', 'noopener,noreferrer')
  } catch (e) {
    ElMessage.error('无法打开服务地址: ' + e.message)
    window.location.href = url
  }
}

// ----------------------------------------------------------------------------
// 加载
// ----------------------------------------------------------------------------
const loadConfig = async () => {
  try {
    const res = await axios.get('/api/v1/standard-services/config')
    configItems.value = res.data.items || []
  } catch (e) {
    ElMessage.error('加载标准服务配置失败: ' + e.message)
  }
}

const loadServices = async () => {
  try {
    const response = await axios.get('/api/v1/services')
    services.value = response.data.services || []
    licenseValid.value = response.data.licenseValid !== false
    licenseErrorCode.value = response.data.licenseErrorCode || null
  } catch (e) {
    ElMessage.error('获取服务状态失败: ' + e.message)
  }
}

const refreshAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadConfig(), loadServices()])
    ElMessage.success('服务状态已更新')
  } finally {
    loading.value = false
  }
}

// ----------------------------------------------------------------------------
// 启停操作（仅 systemd / service-* 容器可控）
// ----------------------------------------------------------------------------
const callAction = async (card, action, label) => {
  card.loading = true
  try {
    const response = await axios.post(`/api/v1/services/${card.key}/${action}`)
    ElMessage.success(response.data.message || `${label}成功`)
    await loadServices()
  } catch (e) {
    ElMessage.error(`${label}失败: ` + (e.response?.data?.detail || e.message))
  } finally {
    card.loading = false
  }
}

const startService = (card) => {
  if (!licenseValid.value) {
    ElMessage.warning('请先完成许可证注册')
    return
  }
  callAction(card, 'start', '启动')
}
const stopService = (card) => callAction(card, 'stop', '停止')
const restartService = (card) => {
  if (!licenseValid.value) {
    ElMessage.warning('请先完成许可证注册')
    return
  }
  callAction(card, 'restart', '重启')
}

// ----------------------------------------------------------------------------
// 配置弹窗
// ----------------------------------------------------------------------------
const openConfigDialog = () => {
  configDraft.value = configItems.value.map((it) => ({ ...it }))
  configVisible.value = true
}

const addRow = () => {
  configDraft.value.push({
    key: '', display: '', description: '', icon: 'Help', port: 0,
  })
}

const removeRow = async (index) => {
  const row = configDraft.value[index]
  try {
    await ElMessageBox.confirm(
      `确认删除 "${row.display || row.key || '该行'}"？仅从展示配置中移除，不会删除容器。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    configDraft.value.splice(index, 1)
  } catch { /* 用户取消 */ }
}

const validateDraft = () => {
  const seen = new Set()
  const KEY_RE = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$/
  for (let i = 0; i < configDraft.value.length; i++) {
    const r = configDraft.value[i]
    const key = (r.key || '').trim()
    if (!key) return `第 ${i + 1} 行：容器名不能为空`
    if (!KEY_RE.test(key)) return `第 ${i + 1} 行：容器名格式非法（仅允许字母、数字、点、下划线、连字符，且首字符为字母或数字）`
    if (seen.has(key)) return `第 ${i + 1} 行：容器名 "${key}" 重复`
    seen.add(key)
    const port = Number(r.port || 0)
    if (!Number.isFinite(port) || port < 0 || port > 65535) return `第 ${i + 1} 行：端口非法`
  }
  return null
}

const saveConfig = async () => {
  const err = validateDraft()
  if (err) { ElMessage.warning(err); return }
  configSaving.value = true
  try {
    const payload = {
      items: configDraft.value.map((r) => ({
        key: (r.key || '').trim(),
        display: (r.display || '').trim() || (r.key || '').trim(),
        description: (r.description || '').trim(),
        icon: (r.icon || '').trim() || 'Help',
        port: Number(r.port || 0),
      })),
    }
    const res = await axios.put('/api/v1/standard-services/config', payload)
    configItems.value = res.data.items || []
    configVisible.value = false
    ElMessage.success('已保存标准服务配置')
    await loadServices()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    configSaving.value = false
  }
}

// ----------------------------------------------------------------------------
// 生命周期
// ----------------------------------------------------------------------------
let timer = null
onMounted(async () => {
  await refreshAll()
  timer = setInterval(loadServices, 30000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
/* ============================================================================
   Dark theme - Arbore Service View
   ============================================================================ */
.services-view {
  padding: 8px 0 24px;
  color: #e2e8f0;
}

/* ----- 顶部工具条 ----- */
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 4px 18px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  margin-bottom: 22px;
}

.toolbar-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: #f1f5f9;
  letter-spacing: 0.4px;
}

.toolbar-title .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.6);
}

.toolbar-title .count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 11px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.gear-btn {
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid rgba(148, 163, 184, 0.25);
  color: #cbd5e1;
  transition: all 0.2s ease;
}
.gear-btn:hover {
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.6);
  background: rgba(16, 185, 129, 0.1);
  transform: rotate(45deg);
}

/* ----- 卡片 ----- */
.service-card {
  margin-bottom: 20px;
  height: 100%;
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.85), rgba(15, 23, 42, 0.85));
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 10px;
  transition: all 0.25s ease;
}
.service-card:hover {
  border-color: rgba(16, 185, 129, 0.45);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(16, 185, 129, 0.15);
}

.service-card :deep(.el-card__header) {
  background: rgba(15, 23, 42, 0.7);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  padding: 14px 18px;
}

.service-card :deep(.el-card__body) {
  background: transparent;
  padding: 16px 18px 18px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.card-icon {
  width: 22px;
  height: 22px;
  color: #10b981;
  flex-shrink: 0;
}
.service-name {
  font-weight: 600;
  font-size: 15px;
  color: #f1f5f9;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.service-info {
  font-size: 13px;
  line-height: 1.6;
}
.service-desc {
  margin: 0 0 12px;
  padding: 10px 12px;
  font-size: 12.5px;
  color: #94a3b8;
  background: rgba(148, 163, 184, 0.06);
  border-left: 3px solid rgba(16, 185, 129, 0.6);
  border-radius: 4px;
}
.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
  font-size: 13px;
}
.meta-label {
  flex-shrink: 0;
  width: 42px;
  color: #94a3b8;
  font-size: 12px;
}
.meta-value { color: #e2e8f0; }
.meta-code {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  padding: 2px 6px;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 3px;
  color: #93c5fd;
}

.service-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed rgba(148, 163, 184, 0.12);
}

.license-alert {
  margin-bottom: 20px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

/* ----- 配置弹窗 ----- */
.services-config-dialog :deep(.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(148, 163, 184, 0.15);
}
.services-config-dialog :deep(.el-dialog__header) {
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  margin: 0;
  padding: 18px 24px;
}
.services-config-dialog :deep(.el-dialog__title) { color: #f1f5f9; }
.services-config-dialog :deep(.el-dialog__body) { padding: 20px 24px; }
.services-config-dialog :deep(.el-dialog__footer) {
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  padding: 14px 24px;
}

.config-tip {
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 13px;
  color: #94a3b8;
  background: rgba(16, 185, 129, 0.06);
  border-left: 3px solid rgba(16, 185, 129, 0.5);
  border-radius: 4px;
  line-height: 1.6;
}

.config-table {
  background: transparent;
}
.config-table :deep(.el-table) {
  background: transparent;
  color: #e2e8f0;
}
.config-table :deep(.el-table th.el-table__cell),
.config-table :deep(.el-table tr) {
  background: rgba(15, 23, 42, 0.7);
}
.config-table :deep(.el-table td.el-table__cell),
.config-table :deep(.el-table th.el-table__cell) {
  border-bottom-color: rgba(148, 163, 184, 0.12);
}
.config-table :deep(.el-table--enable-row-hover .el-table__body tr:hover > td) {
  background: rgba(16, 185, 129, 0.06);
}

.config-add {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 14px;
}
.config-hint {
  font-size: 12px;
  color: #94a3b8;
}

.icon-option {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-option-svg {
  width: 16px;
  height: 16px;
  color: #10b981;
}
</style>
