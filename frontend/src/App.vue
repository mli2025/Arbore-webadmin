<template>
  <!--
    Arbore Web Admin - TUI inspired shell (Catppuccin Mocha)
    ----------------------------------------------------------------------------
    设计要点（中文）：
    - 整体三段式布局：顶部 header（系统/版本信息）→ 中间 tabs+内容 → 底部 status bar
      与 ratatui / TUI 应用一致的"工程感"层级。
    - 顶部 header 采用单像素分隔线，仅展示纯文本信息，无渐变阴影。
    - 标签页采用 [1] [2] ... 数字前缀，配合全局快捷键 1-6 切换。
    - 底部 status bar 固定在视窗底部，左侧显示运行状态指示，右侧显示快捷键提示。
    - 全局快捷键：1-6 切换标签、r 刷新当前页、/ 聚焦搜索（如有）、t 主题占位。

    Design notes (English):
    Three-stripe TUI shell - header / body (tabs + content) / status bar.
    Header is mono-typed and uses a single 1px divider; status bar at the
    bottom mirrors a ratatui app's footer with key hints. Global shortcuts
    1-6 swap tabs, r refreshes the active view via inject-bound callbacks,
    / focuses search where available, t is reserved for future theme cycling.
  -->
  <div class="tui-shell">
    <!-- ============== TOP HEADER ============== -->
    <header class="tui-header">
      <div class="th-left">
        <span class="th-brand">arbore</span>
        <span class="th-sep">·</span>
        <span class="th-title">web admin</span>
      </div>
      <div class="th-right">
        <span class="th-meta">
          host <code>{{ hostName }}</code>
        </span>
        <span class="th-sep">·</span>
        <span class="th-meta">
          build <code class="text-muted">{{ buildTime || '—' }}</code>
        </span>
        <span class="th-sep">·</span>
        <span
          class="th-version"
          :title="buildTime ? `build: ${buildTime}` : ''"
          @click="showChangelog = true"
        >{{ apiVersion }}</span>
      </div>
    </header>

    <!-- ============== UPDATE BANNER ============== -->
    <div v-if="updateInfo.has_update && !updateDismissed" class="tui-banner">
      <span class="tb-icon">!</span>
      <span class="tb-text">
        new version <code>v{{ updateInfo.remote_version }}</code> available
        (current {{ apiVersion }})
      </span>
      <span class="tb-actions">
        <button class="tui-btn tui-btn-accent" @click="showUpdateDialog = true">view</button>
        <button class="tui-btn" @click="updateDismissed = true">dismiss</button>
      </span>
    </div>

    <!-- ============== TAB BAR ============== -->
    <nav class="tui-tabs" role="tablist" aria-label="primary navigation">
      <button
        v-for="(t, i) in tabs"
        :key="t.name"
        :class="['tui-tab', { 'is-active': activeTab === t.name }]"
        @click="activateTab(t.name)"
        role="tab"
        :aria-selected="activeTab === t.name"
      >
        <span class="tt-num">{{ i + 1 }}</span>
        <span class="tt-label">{{ t.label }}</span>
      </button>
    </nav>

    <!-- ============== MAIN BODY ============== -->
    <main class="tui-main">
      <KeepAlive>
        <component :is="activeView" />
      </KeepAlive>
    </main>

    <!-- ============== STATUS BAR ============== -->
    <footer class="tui-status">
      <div class="ts-left">
        <span class="ts-item">
          <span :class="['ts-dot', portainerOk ? 'ok' : 'err']"></span>
          portainer <span :class="portainerOk ? 'text-ok' : 'text-err'">
            {{ portainerOk ? 'reachable' : 'unreachable' }}
          </span>
        </span>
        <span class="ts-item">
          <span :class="['ts-dot', licenseOk ? 'ok' : 'warn']"></span>
          license <span :class="licenseOk ? 'text-ok' : 'text-warn'">
            {{ licenseOk ? 'valid' : 'invalid' }}
          </span>
        </span>
        <span class="ts-item">
          tab <span class="text-accent">{{ activeTabIndex + 1 }}/{{ tabs.length }}</span>
          <span class="text-muted">[{{ activeTabLabel }}]</span>
        </span>
      </div>
      <div class="ts-right">
        <span class="ts-hint">
          <span class="kbd">1</span>-<span class="kbd">{{ tabs.length }}</span>
          <span class="ts-hint-text">switch</span>
        </span>
        <span class="ts-hint">
          <span class="kbd">r</span>
          <span class="ts-hint-text">refresh</span>
        </span>
        <span class="ts-hint">
          <span class="kbd">/</span>
          <span class="ts-hint-text">search</span>
        </span>
        <span class="ts-hint">
          <span class="kbd">?</span>
          <span class="ts-hint-text">help</span>
        </span>
      </div>
    </footer>

    <!-- ============== HELP DIALOG ============== -->
    <el-dialog v-model="showHelp" title="keyboard shortcuts" width="480px" append-to-body>
      <div class="help-list">
        <div class="help-row" v-for="row in helpRows" :key="row.key">
          <span class="kbd">{{ row.key }}</span>
          <span class="help-desc">{{ row.desc }}</span>
        </div>
      </div>
    </el-dialog>

    <!-- ============== UPDATE DIALOG ============== -->
    <el-dialog v-model="showUpdateDialog" title="update" width="500px" :close-on-click-modal="false">
      <div class="update-dialog-body">
        <div class="update-from-to">
          <code>{{ apiVersion }}</code>
          <span class="text-muted">→</span>
          <code class="text-ok">v{{ updateInfo.remote_version }}</code>
        </div>
        <div v-if="updateInfo.build_time" class="text-muted" style="margin-top:6px;font-size:12px;">
          released: <code>{{ updateInfo.build_time }}</code>
        </div>
        <div v-if="updateInfo.changes && updateInfo.changes.length" class="update-changes">
          <h4>changelog</h4>
          <ul>
            <li v-for="(change, idx) in updateInfo.changes" :key="idx">{{ change }}</li>
          </ul>
        </div>
        <el-alert
          v-if="!updateApplying"
          type="warning"
          :closable="false"
          show-icon
          style="margin-top:14px;"
        >
          <template #default>
            applying the update will restart web-admin-api (10~30s downtime)
          </template>
        </el-alert>
        <el-progress
          v-if="updateApplying"
          :percentage="100"
          status="warning"
          :indeterminate="true"
          :duration="3"
          style="margin-top:14px;"
        />
        <div v-if="updateResult" class="update-result" style="margin-top:12px;">
          <el-alert :type="updateResult.success ? 'success' : 'error'" :closable="false" show-icon>
            <template #default>{{ updateResult.message }}</template>
          </el-alert>
        </div>
      </div>
      <template #footer>
        <el-button @click="showUpdateDialog = false" :disabled="updateApplying">cancel</el-button>
        <el-button type="primary" @click="applyUpdate" :loading="updateApplying" :disabled="!!updateResult">
          {{ updateApplying ? 'applying...' : 'apply' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ============== CHANGELOG DIALOG ============== -->
    <el-dialog v-model="showChangelog" title="changelog" width="600px">
      <el-timeline>
        <el-timeline-item
          v-for="item in changelog"
          :key="item.version"
          :timestamp="item.date"
          placement="top"
          :type="item === changelog[0] ? 'primary' : ''"
          :hollow="item !== changelog[0]"
        >
          <div class="cl-row">
            <code>{{ item.version }}</code>
            <span class="cl-title">{{ item.title }}</span>
          </div>
          <ul class="cl-list">
            <li v-for="(change, idx) in item.changes" :key="idx">{{ change }}</li>
          </ul>
        </el-timeline-item>
      </el-timeline>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, provide, shallowRef } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import ServicesView from './components/ServicesView.vue'
import ResourcesView from './components/ResourcesView.vue'
import LogsView from './components/LogsView.vue'
import SystemConfigView from './components/SystemConfigView.vue'
import LicenseView from './components/LicenseView.vue'
import CustomServicesView from './components/CustomServicesView.vue'

// ----------------------------------------------------------------------------
// Tabs definition - keep ordering stable so 1..N keys map predictably
// ----------------------------------------------------------------------------
const tabs = [
  { name: 'services',        label: 'services',  view: ServicesView },
  { name: 'resources',       label: 'resources', view: ResourcesView },
  { name: 'logs',            label: 'logs',      view: LogsView },
  { name: 'system',          label: 'system',    view: SystemConfigView },
  { name: 'license',         label: 'license',   view: LicenseView },
  { name: 'custom-services', label: 'custom',    view: CustomServicesView },
]

const activeTab = ref(tabs[0].name)
const activeView = shallowRef(tabs[0].view)
const activeTabIndex = computed(() => tabs.findIndex(t => t.name === activeTab.value))
const activeTabLabel = computed(() => tabs[activeTabIndex.value]?.label || '')

const activateTab = (name) => {
  const t = tabs.find(x => x.name === name)
  if (!t) return
  activeTab.value = name
  activeView.value = t.view
}

// ----------------------------------------------------------------------------
// Header / status bar state
// ----------------------------------------------------------------------------
const apiVersion = ref('v1.2.0')
const buildTime = ref('')
const hostName = ref(window.location.hostname || 'localhost')
const portainerOk = ref(false)
const licenseOk = ref(true)

// ----------------------------------------------------------------------------
// Update / changelog state
// ----------------------------------------------------------------------------
const updateInfo = reactive({
  has_update: false,
  remote_version: '',
  build_time: '',
  changes: [],
})
const updateDismissed = ref(false)
const showUpdateDialog = ref(false)
const updateApplying = ref(false)
const updateResult = ref(null)
const showChangelog = ref(false)
const showHelp = ref(false)

const changelog = [
  { version: 'v1.2.0', date: '2026-05-01', title: 'TUI redesign + streaming upload',
    changes: [
      'Catppuccin Mocha theme inspired by llmfit, monospace UI',
      'Custom service upload now streams progress via NDJSON',
      'Standard services are now configurable via the gear icon',
      'Image references with uppercase letters are auto-retagged',
    ] },
  { version: 'v1.1.5', date: '2026-03-31', title: 'OTA refinements',
    changes: [
      'OTA check / apply no longer requires the auto-detect toggle',
      'Kanban backend now exposes a direct admin link on port 13051',
    ] },
  { version: 'v1.1.3', date: '2026-03-31', title: 'Service catalog tweaks',
    changes: [
      'Added kanban-frontend (13050) and kanban-backend (13051)',
      'Removed quickchart, pdf-to-png, paddle-ocr, tesseract-ocr cards',
    ] },
  { version: 'v1.1.1', date: '2026-03-13', title: 'Custom service docs',
    changes: [
      'Custom services accept a PDF doc upload',
      'List exposes a quick "doc" button, dialog shows doc state',
      'Inline PDF preview',
    ] },
  { version: 'v1.1.0', date: '2026-01-21', title: 'Custom services GA',
    changes: [
      'Bring-your-own Docker image (tar) deploy flow',
      'Env vars, volumes, memory limit, icon picker',
      'License gate before adding services',
      'Container logs in the detail dialog',
    ] },
]

const helpRows = [
  { key: '1-6',  desc: 'switch tabs (services, resources, logs, system, license, custom)' },
  { key: 'r',    desc: 'refresh data on the active tab (when supported)' },
  { key: '/',    desc: 'focus the search box on the active tab (when supported)' },
  { key: 'esc',  desc: 'close dialogs / clear search' },
  { key: '?',    desc: 'open this help' },
]

// ----------------------------------------------------------------------------
// Provide refresh / search hooks for child views
// ----------------------------------------------------------------------------
const refreshHandlers = new Map()
const searchHandlers = new Map()

provide('setActiveTab', (name) => activateTab(name))
provide('registerRefresh', (tabName, fn) => { refreshHandlers.set(tabName, fn) })
provide('unregisterRefresh', (tabName) => { refreshHandlers.delete(tabName) })
provide('registerSearch', (tabName, fn) => { searchHandlers.set(tabName, fn) })
provide('unregisterSearch', (tabName) => { searchHandlers.delete(tabName) })

// ----------------------------------------------------------------------------
// Keyboard shortcuts
// ----------------------------------------------------------------------------
const isTextInput = (el) => {
  if (!el) return false
  if (el.isContentEditable) return true
  const tag = (el.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  return false
}

const onKeyDown = (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  // While typing in inputs, only ESC keeps a global meaning
  if (isTextInput(e.target) && e.key !== 'Escape') return
  // ESC closes help dialog (other dialogs already handle it themselves)
  if (e.key === 'Escape') {
    if (showHelp.value) showHelp.value = false
    return
  }
  if (e.key === '?') { showHelp.value = true; e.preventDefault(); return }
  if (e.key === 'r' || e.key === 'R') {
    const fn = refreshHandlers.get(activeTab.value)
    if (typeof fn === 'function') {
      try { fn() } catch (err) { console.warn('refresh handler failed', err) }
      e.preventDefault()
    }
    return
  }
  if (e.key === '/') {
    const fn = searchHandlers.get(activeTab.value)
    if (typeof fn === 'function') {
      try { fn() } catch (err) { console.warn('search handler failed', err) }
      e.preventDefault()
    }
    return
  }
  if (e.key === 't' || e.key === 'T') {
    // 主题占位，将来切 Nord / Dracula 时启用
    ElMessage.info('theme: Catppuccin Mocha (single theme for now)')
    return
  }
  // Digit -> tab
  const digit = e.key
  if (digit >= '1' && digit <= '9') {
    const idx = parseInt(digit, 10) - 1
    if (idx < tabs.length) {
      activateTab(tabs[idx].name)
      e.preventDefault()
    }
  }
}

// ----------------------------------------------------------------------------
// Bootstrap
// ----------------------------------------------------------------------------
const fetchVersion = async () => {
  try {
    const r = await axios.get('/api/v1/version')
    if (r.data.version) apiVersion.value = `v${r.data.version}`
    if (r.data.build_time) buildTime.value = r.data.build_time
    portainerOk.value = !!r.data.portainer_reachable
  } catch (e) {
    portainerOk.value = false
    console.error('fetch version failed', e)
  }
}

const fetchLicense = async () => {
  try {
    const r = await axios.get('/api/v1/license')
    licenseOk.value = !!(r.data.valid || r.data.registered)
  } catch (e) {
    licenseOk.value = false
  }
}

const checkUpdate = async () => {
  try {
    const r = await axios.get('/admin-api/api/v1/update/check')
    if (r.data.has_update) {
      updateInfo.has_update = true
      updateInfo.remote_version = r.data.remote_version
      updateInfo.build_time = r.data.build_time
      updateInfo.changes = r.data.changes || []
    }
  } catch (e) {
    // Silent: OTA endpoint may be disabled in offline deployments
  }
}

const applyUpdate = async () => {
  updateApplying.value = true
  updateResult.value = null
  try {
    const r = await axios.post('/admin-api/api/v1/update/apply')
    updateResult.value = { success: true, message: r.data.message || 'restarting service...' }
    setTimeout(() => window.location.reload(), 15000)
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || 'update failed'
    updateResult.value = { success: false, message: msg }
  } finally {
    updateApplying.value = false
  }
}

let statusTimer = null
onMounted(async () => {
  document.addEventListener('keydown', onKeyDown)
  await Promise.all([fetchVersion(), fetchLicense()])
  setTimeout(checkUpdate, 3000)
  statusTimer = setInterval(() => {
    fetchVersion()
    fetchLicense()
  }, 30000)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeyDown)
  if (statusTimer) clearInterval(statusTimer)
})
</script>

<style scoped>
/* TUI shell (Catppuccin Mocha) ============================================ */
.tui-shell {
  display: grid;
  grid-template-rows: auto auto auto 1fr auto;
  min-height: 100vh;
  background: var(--bg-base);
  color: var(--fg-text);
  font-family: var(--font-mono);
}

/* ----- header ----- */
.tui-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 18px;
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  letter-spacing: 0.4px;
}
.th-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.th-brand {
  color: var(--accent);
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: lowercase;
}
.th-brand::before {
  content: '◆ ';
  color: var(--accent-strong);
  font-weight: normal;
}
.th-title {
  color: var(--fg-subtext);
  text-transform: lowercase;
  letter-spacing: 1px;
}
.th-sep { color: var(--fg-faint); }
.th-right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.th-meta { color: var(--fg-muted); }
.th-version {
  margin-left: 6px;
  padding: 2px 8px;
  border: 1px solid var(--accent);
  color: var(--accent);
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: all 0.15s;
}
.th-version:hover {
  background: var(--accent-soft);
  color: var(--accent-strong);
}

/* ----- update banner ----- */
.tui-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 18px;
  background: rgba(250, 179, 135, 0.08);
  border-bottom: 1px solid var(--mocha-peach);
  color: var(--mocha-peach);
  font-size: 12.5px;
}
.tb-icon {
  width: 18px; height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--mocha-peach);
  color: var(--bg-base);
  font-weight: 700;
  border-radius: 50%;
  font-size: 11px;
}
.tb-text { color: var(--fg-text); }
.tb-actions { margin-left: auto; display: flex; gap: 6px; }
.tui-btn {
  font-family: var(--font-mono);
  background: transparent;
  color: var(--fg-text);
  border: 1px solid var(--border-strong);
  padding: 2px 10px;
  font-size: 12px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  letter-spacing: 0.4px;
}
.tui-btn:hover { border-color: var(--accent); color: var(--accent); }
.tui-btn-accent {
  background: var(--accent);
  color: var(--bg-base);
  border-color: var(--accent);
  font-weight: 600;
}
.tui-btn-accent:hover { background: var(--accent-strong); border-color: var(--accent-strong); color: var(--bg-base); }

/* ----- tabs ----- */
.tui-tabs {
  display: flex;
  align-items: stretch;
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--border);
  padding: 0 8px;
  overflow-x: auto;
}
.tui-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--fg-muted);
  font-family: var(--font-mono);
  font-size: 12.5px;
  padding: 10px 14px;
  cursor: pointer;
  letter-spacing: 0.4px;
  text-transform: lowercase;
  transition: color 0.12s, border-color 0.12s, background 0.12s;
}
.tui-tab:hover {
  color: var(--accent-strong);
  background: rgba(180, 190, 254, 0.05);
}
.tui-tab.is-active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  background: var(--accent-soft);
}
.tt-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  font-size: 10.5px;
  color: var(--fg-faint);
  font-weight: 600;
}
.tui-tab.is-active .tt-num { color: var(--accent); }
.tt-label { font-weight: 500; }

/* ----- main ----- */
.tui-main {
  padding: 16px 22px 24px;
  overflow-y: auto;
  max-width: 1500px;
  width: 100%;
  margin: 0 auto;
}

/* ----- status bar ----- */
.tui-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 18px;
  background: var(--bg-mantle);
  border-top: 1px solid var(--border);
  font-size: 11.5px;
  color: var(--fg-muted);
  letter-spacing: 0.3px;
  position: sticky;
  bottom: 0;
}
.ts-left, .ts-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.ts-item, .ts-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ts-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--fg-faint);
  display: inline-block;
}
.ts-dot.ok   { background: var(--status-ok); box-shadow: 0 0 6px rgba(166,227,161,0.5); }
.ts-dot.warn { background: var(--status-warn); }
.ts-dot.err  { background: var(--status-err); }
.ts-hint-text { color: var(--fg-faint); font-size: 11px; }

/* ----- help dialog ----- */
.help-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.help-row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.help-desc { color: var(--fg-subtext); font-size: 13px; }

/* ----- update / changelog ----- */
.update-from-to {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 14px;
}
.update-changes h4 {
  margin: 14px 0 6px;
  color: var(--fg-text);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.update-changes ul {
  margin: 0;
  padding-left: 20px;
  color: var(--fg-subtext);
  font-size: 12.5px;
  line-height: 1.7;
}
.cl-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.cl-title {
  font-weight: 600;
  color: var(--fg-text);
  font-size: 13px;
}
.cl-list {
  margin: 0;
  padding-left: 18px;
  color: var(--fg-subtext);
  font-size: 12.5px;
  line-height: 1.75;
}
</style>
