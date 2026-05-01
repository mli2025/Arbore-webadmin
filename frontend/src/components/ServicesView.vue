<template>
  <!--
    Services View - Catppuccin Mocha (TUI inspired)
    ----------------------------------------------------------------------------
    本视图采用密集表格而非卡片，参考 ratatui / llmfit 的 list 视图：
    - 单行列出每个标准服务，状态用彩色 LED 字符表示（●）
    - 第一列为索引（[01]、[02]…），呼应终端 list 的视觉
    - 顶部 toolbar 仅一条横向单像素线 + 关键操作（搜索 / 刷新 / 配置齿轮）
    - 底部留一行汇总信息（运行/总数/未找到）作为子状态条，与外壳的全局状态条
      形成层级
  -->
  <div class="services-view">
    <!-- License banner -->
    <el-alert
      v-if="!licenseValid && licenseErrorCode"
      type="warning"
      :closable="false"
      show-icon
      class="license-alert"
    >
      <template #title>
        license invalid - standard services cannot be started or restarted.
        please register on the license tab.
      </template>
    </el-alert>

    <!-- Toolbar -->
    <div class="sv-toolbar">
      <div class="svt-left">
        <span class="svt-title">standard services</span>
        <span class="svt-count">{{ cards.length }}</span>
      </div>
      <div class="svt-search">
        <el-input
          v-model="searchText"
          ref="searchInput"
          placeholder="filter… (press / to focus)"
          size="small"
          clearable
        >
          <template #prefix>
            <span class="svt-search-prefix">/</span>
          </template>
        </el-input>
      </div>
      <div class="svt-actions">
        <el-button size="small" :icon="RefreshRight" :loading="loading" @click="refreshAll">
          refresh
        </el-button>
        <el-tooltip content="manage standard services" placement="bottom">
          <el-button size="small" :icon="Setting" @click="openConfigDialog">
            configure
          </el-button>
        </el-tooltip>
      </div>
    </div>

    <!-- Table (dense) -->
    <div class="sv-table-wrap">
      <el-table
        :data="filteredCards"
        size="small"
        :show-header="true"
        empty-text="no services configured. press 'configure' to add."
        row-class-name="sv-row"
      >
        <el-table-column label="#" width="46" align="right">
          <template #default="{ $index }">
            <span class="text-faint">{{ String($index + 1).padStart(2, '0') }}</span>
          </template>
        </el-table-column>

        <el-table-column label="status" width="110">
          <template #default="{ row }">
            <span :class="['status-led', 'led-' + statusKind(row.status)]">●</span>
            <span class="status-text">{{ row.status || 'unknown' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="service" min-width="220">
          <template #default="{ row }">
            <div class="sv-name-cell">
              <component :is="resolveIcon(row.icon)" class="sv-name-icon" />
              <div class="sv-name-text">
                <div class="sv-name-line">{{ row.display || row.key }}</div>
                <div class="sv-name-desc">{{ row.description || '—' }}</div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="container" min-width="180">
          <template #default="{ row }">
            <code class="sv-code">{{ row.key }}</code>
          </template>
        </el-table-column>

        <el-table-column label="port" width="100">
          <template #default="{ row }">
            <span v-if="row.port" class="text-info mono">{{ row.port }}</span>
            <span v-else class="text-faint">—</span>
          </template>
        </el-table-column>

        <el-table-column label="health" width="100">
          <template #default="{ row }">
            <span v-if="row.health && row.health !== 'unknown'"
                  :class="row.health === 'healthy' ? 'text-ok' : 'text-warn'">
              {{ row.health }}
            </span>
            <span v-else class="text-faint">—</span>
          </template>
        </el-table-column>

        <el-table-column label="actions" min-width="220" align="right">
          <template #default="{ row }">
            <div class="sv-actions">
              <button
                class="sv-act"
                :class="{ disabled: row.status !== 'running' || !row.port }"
                :disabled="row.status !== 'running' || !row.port"
                @click="openService(row)"
              >open</button>

              <button
                v-if="row.canControl && row.status !== 'running'"
                class="sv-act sv-act-ok"
                :disabled="!licenseValid || row.loading"
                @click="startService(row)"
              >start</button>

              <button
                v-if="row.canControl && row.status === 'running'"
                class="sv-act sv-act-warn"
                :disabled="row.loading"
                @click="stopService(row)"
              >stop</button>

              <button
                v-if="row.canControl && row.status === 'running'"
                class="sv-act"
                :disabled="!licenseValid || row.loading"
                @click="restartService(row)"
              >restart</button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Sub-status line -->
    <div class="sv-substatus">
      <span class="ss-item">
        <span class="status-led led-ok">●</span>
        running <span class="text-ok">{{ statsRunning }}</span>
      </span>
      <span class="ss-item">
        <span class="status-led led-err">●</span>
        stopped <span class="text-err">{{ statsStopped }}</span>
      </span>
      <span class="ss-item">
        <span class="status-led led-info">●</span>
        not_found <span class="text-info">{{ statsMissing }}</span>
      </span>
      <span class="ss-item">
        total <span class="text-accent">{{ cards.length }}</span>
      </span>
      <span class="ss-item ss-spacer"></span>
      <span class="ss-item text-muted" v-if="searchText">
        filter: <code>{{ searchText }}</code> · {{ filteredCards.length }} match
      </span>
    </div>

    <!-- Configuration dialog -->
    <el-dialog
      v-model="configVisible"
      title="manage standard services"
      width="900px"
      :close-on-click-modal="false"
    >
      <div class="config-tip">
        edit display metadata only — container name, label, description, icon
        and host port. <span class="text-warn">no containers are created or
        removed here.</span>
      </div>

      <el-table :data="configDraft" border size="small"
                empty-text="no entries — click + add to create one">
        <el-table-column label="container (key)" min-width="170">
          <template #default="{ row }">
            <el-input v-model="row.key" placeholder="arbore-flow"
                      size="small" spellcheck="false" />
          </template>
        </el-table-column>
        <el-table-column label="display name" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.display" placeholder="workflow service" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="description" min-width="200">
          <template #default="{ row }">
            <el-input v-model="row.description" placeholder="optional" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="icon" width="170">
          <template #default="{ row }">
            <el-select v-model="row.icon" size="small" placeholder="icon">
              <el-option v-for="opt in iconOptions"
                         :key="opt.value" :label="opt.label" :value="opt.value">
                <span class="icon-option">
                  <component :is="opt.value" class="icon-option-svg" />
                  <span>{{ opt.label }}</span>
                </span>
              </el-option>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="host port" width="120">
          <template #default="{ row }">
            <el-input-number v-model="row.port" :min="0" :max="65535"
                             :step="1" :controls="false" size="small"
                             placeholder="0" style="width: 100%;" />
          </template>
        </el-table-column>
        <el-table-column label="" width="60" align="center">
          <template #default="{ $index }">
            <button class="sv-act sv-act-danger sv-act-tiny"
                    @click="removeRow($index)">×</button>
          </template>
        </el-table-column>
      </el-table>

      <div class="config-add">
        <el-button :icon="Plus" plain size="small" @click="addRow">+ add</el-button>
        <span class="config-hint text-muted">port = 0 means no web entry (e.g. databases)</span>
      </div>

      <template #footer>
        <el-button @click="configVisible = false" :disabled="configSaving">cancel</el-button>
        <el-button type="primary" :loading="configSaving" @click="saveConfig">save</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount, markRaw, inject, nextTick } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  RefreshRight, Setting, Plus,
  Connection, Grid, Coin, DataLine, Cpu, ChatDotRound, Monitor, Service,
  Box, Promotion, Tools, Files, Help, DataAnalysis,
} from '@element-plus/icons-vue'

const TAB_NAME = 'services'

// ----------------------------------------------------------------------------
// Reactive state
// ----------------------------------------------------------------------------
const services = ref([])
const configItems = ref([])
const loading = ref(false)
const licenseValid = ref(true)
const licenseErrorCode = ref(null)

const configVisible = ref(false)
const configSaving = ref(false)
const configDraft = ref([])
const searchText = ref('')
const searchInput = ref(null)

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
  { value: 'Connection', label: 'workflow' },
  { value: 'Grid',       label: 'app' },
  { value: 'Coin',       label: 'database' },
  { value: 'DataLine',   label: 'vector db' },
  { value: 'Cpu',        label: 'ai model' },
  { value: 'ChatDotRound', label: 'ai chat' },
  { value: 'Monitor',    label: 'frontend / kanban' },
  { value: 'Service',    label: 'backend' },
  { value: 'Box',        label: 'container' },
  { value: 'Promotion',  label: 'message' },
  { value: 'Tools',      label: 'tools' },
  { value: 'Files',      label: 'files' },
  { value: 'DataAnalysis', label: 'analytics' },
  { value: 'Help',       label: 'other' },
]
const resolveIcon = (name) => ICONS[name] || ICONS.Help

// ----------------------------------------------------------------------------
// Derived: cards = service config + runtime status
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

const filteredCards = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return cards.value
  return cards.value.filter(c =>
    c.key.toLowerCase().includes(q) ||
    (c.display || '').toLowerCase().includes(q) ||
    (c.description || '').toLowerCase().includes(q) ||
    String(c.port || '').includes(q),
  )
})

const statsRunning = computed(() => cards.value.filter(c => c.status === 'running').length)
const statsStopped = computed(() => cards.value.filter(c => ['stopped', 'exited'].includes(c.status)).length)
const statsMissing = computed(() => cards.value.filter(c => c.status === 'not_found').length)

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------
const statusKind = (status) => {
  if (status === 'running') return 'ok'
  if (status === 'stopped' || status === 'exited') return 'err'
  if (status === 'restarting') return 'warn'
  return 'info'
}

const baseUrl = () => `${window.location.protocol}//${window.location.hostname}`

const openService = (card) => {
  if (!card.port) { ElMessage.info('this service has no web entry'); return }
  const url = `${baseUrl()}:${card.port}`
  try { window.open(url, '_blank', 'noopener,noreferrer') } catch (e) {
    window.location.href = url
  }
}

// ----------------------------------------------------------------------------
// Data loading
// ----------------------------------------------------------------------------
const loadConfig = async () => {
  try {
    const r = await axios.get('/api/v1/standard-services/config')
    configItems.value = r.data.items || []
  } catch (e) {
    ElMessage.error('failed to load standard services config: ' + e.message)
  }
}

const loadServices = async () => {
  try {
    const r = await axios.get('/api/v1/services')
    services.value = r.data.services || []
    licenseValid.value = r.data.licenseValid !== false
    licenseErrorCode.value = r.data.licenseErrorCode || null
  } catch (e) {
    ElMessage.error('failed to fetch services: ' + e.message)
  }
}

const refreshAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadConfig(), loadServices()])
    ElMessage.success('refreshed')
  } finally {
    loading.value = false
  }
}

// ----------------------------------------------------------------------------
// Start / stop / restart
// ----------------------------------------------------------------------------
const callAction = async (card, action, label) => {
  card.loading = true
  try {
    const r = await axios.post(`/api/v1/services/${card.key}/${action}`)
    ElMessage.success(r.data.message || `${label} ok`)
    await loadServices()
  } catch (e) {
    ElMessage.error(`${label} failed: ` + (e.response?.data?.detail || e.message))
  } finally {
    card.loading = false
  }
}

const startService = (c) => {
  if (!licenseValid.value) { ElMessage.warning('register license first'); return }
  callAction(c, 'start', 'start')
}
const stopService = (c) => callAction(c, 'stop', 'stop')
const restartService = (c) => {
  if (!licenseValid.value) { ElMessage.warning('register license first'); return }
  callAction(c, 'restart', 'restart')
}

// ----------------------------------------------------------------------------
// Configuration dialog
// ----------------------------------------------------------------------------
const openConfigDialog = () => {
  configDraft.value = configItems.value.map(it => ({ ...it }))
  configVisible.value = true
}

const addRow = () => {
  configDraft.value.push({ key: '', display: '', description: '', icon: 'Help', port: 0 })
}

const removeRow = async (index) => {
  const row = configDraft.value[index]
  try {
    await ElMessageBox.confirm(
      `remove "${row.display || row.key || 'this row'}"? this only removes the display entry, no container is touched.`,
      'remove entry',
      { type: 'warning', confirmButtonText: 'remove', cancelButtonText: 'cancel' },
    )
    configDraft.value.splice(index, 1)
  } catch { /* user cancelled */ }
}

const validateDraft = () => {
  const seen = new Set()
  const KEY_RE = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$/
  for (let i = 0; i < configDraft.value.length; i++) {
    const r = configDraft.value[i]
    const key = (r.key || '').trim()
    if (!key) return `row ${i + 1}: key is required`
    if (!KEY_RE.test(key)) return `row ${i + 1}: invalid key format`
    if (seen.has(key)) return `row ${i + 1}: duplicate key "${key}"`
    seen.add(key)
    const port = Number(r.port || 0)
    if (!Number.isFinite(port) || port < 0 || port > 65535) return `row ${i + 1}: invalid port`
  }
  return null
}

const saveConfig = async () => {
  const err = validateDraft()
  if (err) { ElMessage.warning(err); return }
  configSaving.value = true
  try {
    const payload = {
      items: configDraft.value.map(r => ({
        key: (r.key || '').trim(),
        display: (r.display || '').trim() || (r.key || '').trim(),
        description: (r.description || '').trim(),
        icon: (r.icon || '').trim() || 'Help',
        port: Number(r.port || 0),
      })),
    }
    const r = await axios.put('/api/v1/standard-services/config', payload)
    configItems.value = r.data.items || []
    configVisible.value = false
    ElMessage.success('saved')
    await loadServices()
  } catch (e) {
    ElMessage.error('save failed: ' + (e.response?.data?.detail || e.message))
  } finally {
    configSaving.value = false
  }
}

// ----------------------------------------------------------------------------
// Lifecycle + global keyboard hooks via App.vue provide()
// ----------------------------------------------------------------------------
const registerRefresh   = inject('registerRefresh',   null)
const unregisterRefresh = inject('unregisterRefresh', null)
const registerSearch    = inject('registerSearch',    null)
const unregisterSearch  = inject('unregisterSearch',  null)

const focusSearch = async () => {
  await nextTick()
  // El-input ref exposes .focus()
  const input = searchInput.value
  if (input && typeof input.focus === 'function') input.focus()
}

let timer = null
onMounted(async () => {
  await refreshAll()
  timer = setInterval(loadServices, 30000)
  if (registerRefresh) registerRefresh(TAB_NAME, refreshAll)
  if (registerSearch)  registerSearch(TAB_NAME, focusSearch)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (unregisterRefresh) unregisterRefresh(TAB_NAME)
  if (unregisterSearch)  unregisterSearch(TAB_NAME)
})
</script>

<style scoped>
/* Catppuccin Mocha - dense, ratatui inspired ============================== */
.services-view {
  font-family: var(--font-mono);
  color: var(--fg-text);
}

.license-alert { margin-bottom: 12px; }

/* ---- toolbar ---- */
.sv-toolbar {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 14px;
  padding: 8px 12px;
  background: var(--bg-mantle);
  border: 1px solid var(--border);
  border-bottom: none;
  border-radius: var(--radius-tile) var(--radius-tile) 0 0;
}
.svt-left { display: flex; align-items: baseline; gap: 10px; }
.svt-title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--fg-muted);
  font-weight: 600;
}
.svt-title::before {
  content: '┃';
  color: var(--accent);
  margin-right: 8px;
}
.svt-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 18px;
  padding: 0 6px;
  font-size: 11px;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid var(--accent);
  border-radius: var(--radius-pill);
}
.svt-search { max-width: 320px; }
.svt-search-prefix {
  color: var(--accent);
  font-weight: 700;
  font-family: var(--font-mono);
}
.svt-actions { display: flex; gap: 6px; }

/* ---- table wrapper ---- */
.sv-table-wrap {
  border: 1px solid var(--border);
  border-radius: 0 0 var(--radius-tile) var(--radius-tile);
  overflow: hidden;
  background: var(--bg-base);
}
.sv-table-wrap :deep(.el-table) {
  --el-table-row-hover-bg-color: var(--bg-surface);
}

/* ---- name cell ---- */
.sv-name-cell {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
}
.sv-name-icon {
  width: 16px;
  height: 16px;
  margin-top: 2px;
  color: var(--accent);
  flex-shrink: 0;
}
.sv-name-text { min-width: 0; }
.sv-name-line {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-text);
  letter-spacing: 0.2px;
}
.sv-name-desc {
  font-size: 11.5px;
  color: var(--fg-muted);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---- code-like container name ---- */
.sv-code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--mocha-blue);
  background: var(--bg-crust);
  border: 1px solid var(--border);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

/* ---- LED status ---- */
.status-led {
  display: inline-block;
  font-size: 10px;
  margin-right: 6px;
  vertical-align: middle;
  line-height: 1;
}
.led-ok   { color: var(--status-ok);   text-shadow: 0 0 6px rgba(166,227,161,0.6); }
.led-err  { color: var(--status-err); }
.led-warn { color: var(--status-warn); }
.led-info { color: var(--status-info); }
.status-text {
  text-transform: lowercase;
  font-size: 12px;
  letter-spacing: 0.4px;
}

/* ---- action buttons (inline, terminal-style) ---- */
.sv-actions {
  display: inline-flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.sv-act {
  font-family: var(--font-mono);
  background: transparent;
  color: var(--fg-subtext);
  border: 1px solid var(--border-strong);
  padding: 2px 10px;
  font-size: 11.5px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  letter-spacing: 0.4px;
  text-transform: lowercase;
  line-height: 1.5;
  transition: color 0.12s, border-color 0.12s, background 0.12s;
}
.sv-act:hover:not(:disabled):not(.disabled) {
  color: var(--accent);
  border-color: var(--accent);
}
.sv-act:disabled, .sv-act.disabled {
  color: var(--fg-faint);
  border-color: var(--border);
  cursor: not-allowed;
  opacity: 0.5;
}
.sv-act-ok {
  color: var(--mocha-green);
  border-color: var(--mocha-green);
}
.sv-act-ok:hover:not(:disabled) {
  background: rgba(166,227,161,0.1);
  color: var(--mocha-green);
}
.sv-act-warn {
  color: var(--mocha-peach);
  border-color: var(--mocha-peach);
}
.sv-act-warn:hover:not(:disabled) {
  background: rgba(250,179,135,0.1);
  color: var(--mocha-peach);
}
.sv-act-danger {
  color: var(--mocha-red);
  border-color: var(--mocha-red);
}
.sv-act-danger:hover:not(:disabled) {
  background: rgba(243,139,168,0.1);
}
.sv-act-tiny {
  padding: 0;
  width: 24px;
  height: 22px;
  font-size: 14px;
  line-height: 1;
  font-weight: 700;
}

/* ---- sub-status row ---- */
.sv-substatus {
  display: flex;
  gap: 18px;
  align-items: center;
  padding: 6px 12px;
  margin-top: 6px;
  background: var(--bg-mantle);
  border: 1px solid var(--border);
  border-radius: var(--radius-tile);
  font-size: 11.5px;
  color: var(--fg-muted);
  letter-spacing: 0.3px;
}
.ss-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ss-spacer { flex: 1; }

/* ---- configuration dialog ---- */
.config-tip {
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--fg-subtext);
  background: var(--accent-soft);
  border-left: 2px solid var(--accent);
}
.config-add {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 10px;
}
.config-hint { font-size: 11.5px; }
.icon-option {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-option-svg {
  width: 14px;
  height: 14px;
  color: var(--accent);
}

/* ---- override el-table row padding for density ---- */
.services-view :deep(.el-table .el-table__row) {
  background: transparent;
}
.services-view :deep(.el-table .cell) {
  padding-left: 12px;
  padding-right: 12px;
}
.services-view :deep(.el-table .el-table__cell) {
  padding: 8px 0;
}
</style>
