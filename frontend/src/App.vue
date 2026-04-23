<template>
  <!--
    Arbore Web Admin 根组件
    Root component of Arbore Web Admin

    设计目标（中文）:
    - 统一布局：使用 Element Plus 的布局容器组件构建头部 + 主内容区结构，
      保证不同页面在视觉和交互上的一致性。
    - 模块分栏：通过标签页将多个功能区域（服务状态、资源监控、日志、配置、
      许可证、自定义服务）聚合在一处，便于运维人员快速切换。
    - 版本可见：右上角展示 API 版本和构建时间，便于问题排查时确认部署版本。

    Design goals (English):
    - Unified layout: rely on Element Plus layout components to create a
      consistent header + content shell so that each feature view behaves
      as a pluggable module inside the same frame.
    - Tab based navigation: major operational domains (service states,
      resource metrics, logs, configuration, license management and
      custom services) are exposed as first‑class tabs for quick access.
    - Version visibility: show API version and build timestamp in the
      header to help support engineers identify the running build quickly.
  -->
  <el-container class="admin-container">
    <el-header class="admin-header">
      <div class="header-content">
        <div class="logo-section">
          <div class="logo">
            <img src="/logo.png" alt="Arbore Logo" />
          </div>
          <div>
            <div class="logo-text">arbore</div>
            <div class="logo-subtitle">AI Host 管理控制台</div>
          </div>
        </div>
        <div class="version-badge" :title="buildTime ? `构建时间: ${buildTime}` : ''" @click="showChangelog = true" style="cursor: pointer;">
          {{ apiVersion }}
        </div>
      </div>
    </el-header>

    <!-- 更新提示横幅 -->
    <div v-if="updateInfo.has_update && !updateDismissed" class="update-banner">
      <div class="update-banner-content">
        <span class="update-icon">🔔</span>
        <span>发现新版本 <strong>v{{ updateInfo.remote_version }}</strong>，当前版本 {{ apiVersion }}</span>
        <div class="update-actions">
          <el-button type="primary" size="small" @click="showUpdateDialog = true">查看更新</el-button>
          <el-button size="small" @click="updateDismissed = true">稍后提醒</el-button>
        </div>
      </div>
    </div>

    <!-- 更新详情弹窗 -->
    <el-dialog v-model="showUpdateDialog" title="版本更新" width="500px" :close-on-click-modal="false">
      <div class="update-dialog-body">
        <div class="update-version-info">
          <div class="update-from-to">
            <el-tag type="info">{{ apiVersion }}</el-tag>
            <span class="update-arrow">→</span>
            <el-tag type="success">v{{ updateInfo.remote_version }}</el-tag>
          </div>
          <div v-if="updateInfo.build_time" class="update-time">发布时间：{{ updateInfo.build_time }}</div>
        </div>
        <div v-if="updateInfo.changes && updateInfo.changes.length" class="update-changes">
          <h4>更新内容：</h4>
          <ul>
            <li v-for="(change, idx) in updateInfo.changes" :key="idx">{{ change }}</li>
          </ul>
        </div>
        <el-alert
          v-if="!updateApplying"
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 16px;"
        >
          <template #default>
            更新将自动下载新版本文件并重启后端服务，期间页面会短暂无法访问（约10~30秒）。
          </template>
        </el-alert>
        <el-progress
          v-if="updateApplying"
          :percentage="100"
          status="warning"
          :indeterminate="true"
          :duration="3"
          style="margin-top: 16px;"
        />
        <div v-if="updateResult" class="update-result" style="margin-top: 12px;">
          <el-alert :type="updateResult.success ? 'success' : 'error'" :closable="false" show-icon>
            <template #default>{{ updateResult.message }}</template>
          </el-alert>
        </div>
      </div>
      <template #footer>
        <el-button @click="showUpdateDialog = false" :disabled="updateApplying">取消</el-button>
        <el-button type="primary" @click="applyUpdate" :loading="updateApplying" :disabled="!!updateResult">
          {{ updateApplying ? '更新中...' : '立即更新' }}
        </el-button>
      </template>
    </el-dialog>

    <el-main class="admin-main">
      <el-tabs v-model="activeTab" @tab-click="handleTabClick" class="arbore-tabs">
        <el-tab-pane label="服务状态" name="services">
          <ServicesView />
        </el-tab-pane>
        <el-tab-pane label="资源监控" name="resources">
          <ResourcesView />
        </el-tab-pane>
        <el-tab-pane label="日志查看" name="logs">
          <LogsView />
        </el-tab-pane>
        <el-tab-pane label="系统配置" name="system">
          <SystemConfigView />
        </el-tab-pane>
        <el-tab-pane label="许可证" name="license">
          <LicenseView />
        </el-tab-pane>
        <el-tab-pane label="自定义服务" name="custom-services">
          <CustomServicesView />
        </el-tab-pane>
      </el-tabs>
    </el-main>

    <!-- 版本更新说明弹窗 -->
    <el-dialog v-model="showChangelog" title="版本更新说明" width="600px" :close-on-click-modal="true">
      <el-timeline>
        <el-timeline-item
          v-for="item in changelog"
          :key="item.version"
          :timestamp="item.date"
          placement="top"
          :type="item === changelog[0] ? 'primary' : ''"
          :hollow="item !== changelog[0]"
        >
          <el-card shadow="never" class="changelog-card">
            <template #header>
              <div class="changelog-header">
                <el-tag :type="item === changelog[0] ? '' : 'info'" size="small">{{ item.version }}</el-tag>
                <span class="changelog-title">{{ item.title }}</span>
              </div>
            </template>
            <ul class="changelog-list">
              <li v-for="(change, idx) in item.changes" :key="idx">{{ change }}</li>
            </ul>
          </el-card>
        </el-timeline-item>
      </el-timeline>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { ref, reactive, onMounted, provide } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import ServicesView from './components/ServicesView.vue'
import ResourcesView from './components/ResourcesView.vue'
import LogsView from './components/LogsView.vue'
import SystemConfigView from './components/SystemConfigView.vue'
import LicenseView from './components/LicenseView.vue'
import CustomServicesView from './components/CustomServicesView.vue'

const activeTab = ref('services')
const apiVersion = ref('v1.1.5')
const buildTime = ref('')
const showChangelog = ref(false)

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

const changelog = [
  {
    version: 'v1.1.5',
    date: '2026-03-31',
    title: 'OTA 与服务访问优化',
    changes: [
      'OTA：「立即检查」「立即更新」不再依赖「启用自动检测」开关，仅需填写更新服务器地址',
      '看板后端「访问服务」可直接打开 13051 管理界面',
    ]
  },
  {
    version: 'v1.1.3',
    date: '2026-03-31',
    title: '服务状态调整',
    changes: [
      '新增看板前端服务（端口 13050）和看板后端服务（端口 13051）',
      '移除图表生成服务、PDF转PNG服务、PaddleOCR服务、Tesseract OCR服务',
    ]
  },
  {
    version: 'v1.1.1',
    date: '2026-03-13',
    title: '自定义服务文档支持',
    changes: [
      '自定义服务支持上传PDF说明文档',
      '服务列表新增「文档」快捷按钮，可在线查看PDF',
      '编辑服务时可上传/替换/删除说明文档',
      '服务详情弹窗展示文档状态',
      '新增版本更新说明弹窗（点击版本号查看）'
    ]
  },
  {
    version: 'v1.1.0',
    date: '2026-01-21',
    title: '自定义服务管理',
    changes: [
      '新增自定义服务管理模块，支持上传Docker镜像部署',
      '支持环境变量、卷挂载、内存限制等容器配置',
      '支持服务图标选择、容器内外端口映射',
      '集成许可证校验，授权后方可添加服务',
      '服务详情弹窗可查看容器日志'
    ]
  }
]

provide('setActiveTab', (name) => {
  activeTab.value = name
})

const handleTabClick = (tab) => {
  console.log('Tab clicked:', tab.name)
}

const checkUpdate = async () => {
  try {
    const res = await axios.get('/admin-api/api/v1/update/check')
    if (res.data.has_update) {
      updateInfo.has_update = true
      updateInfo.remote_version = res.data.remote_version
      updateInfo.build_time = res.data.build_time
      updateInfo.changes = res.data.changes || []
    }
  } catch (error) {
    console.error('Update check failed:', error)
  }
}

const applyUpdate = async () => {
  updateApplying.value = true
  updateResult.value = null
  try {
    const res = await axios.post('/admin-api/api/v1/update/apply')
    updateResult.value = { success: true, message: res.data.message || '更新成功，服务正在重启...' }
    setTimeout(() => {
      window.location.reload()
    }, 15000)
  } catch (error) {
    const msg = error.response?.data?.detail || error.message || '更新失败'
    updateResult.value = { success: false, message: msg }
  } finally {
    updateApplying.value = false
  }
}

onMounted(async () => {
  try {
    const response = await axios.get('/api/v1/version')
    if (response.data.version) {
      apiVersion.value = `v${response.data.version}`
    }
    if (response.data.build_time) {
      buildTime.value = response.data.build_time
    }
  } catch (error) {
    console.error('Failed to fetch version:', error)
  }

  setTimeout(checkUpdate, 3000)
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0f172a; /* Arbore品牌深色背景 */
  color: #f1f5f9;
  min-height: 100vh;
}

.admin-container {
  min-height: 100vh;
  background: #0f172a;
}

.admin-header {
  background: rgba(15, 23, 42, 0.95);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  padding: 20px 40px;
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-content {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 15px;
}

.logo {
  width: 50px;
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.logo img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.logo-text {
  font-size: 24px;
  font-weight: 600;
  color: #f1f5f9;
  letter-spacing: -0.5px;
}

.logo-subtitle {
  font-size: 14px;
  color: #94a3b8;
  margin-top: 2px;
}

.version-badge {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 0.85em;
  font-weight: 500;
  transition: background 0.2s;
}

.version-badge:hover {
  background: rgba(16, 185, 129, 0.35);
}

.update-banner {
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.15), rgba(245, 158, 11, 0.08));
  border-bottom: 1px solid rgba(245, 158, 11, 0.3);
  padding: 10px 40px;
  position: relative;
  z-index: 99;
}

.update-banner-content {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: #fbbf24;
}

.update-icon {
  font-size: 18px;
}

.update-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.update-dialog-body {
  color: #cbd5e1;
}

.update-version-info {
  text-align: center;
  margin-bottom: 16px;
}

.update-from-to {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  font-size: 16px;
}

.update-arrow {
  font-size: 20px;
  color: #10b981;
}

.update-time {
  margin-top: 8px;
  font-size: 13px;
  color: #94a3b8;
}

.update-changes h4 {
  margin: 0 0 8px 0;
  color: #f1f5f9;
  font-size: 14px;
}

.update-changes ul {
  margin: 0;
  padding-left: 20px;
  line-height: 1.8;
  font-size: 13px;
}

.changelog-card {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.15);
}

.changelog-card :deep(.el-card__header) {
  padding: 10px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.changelog-card :deep(.el-card__body) {
  padding: 12px 16px;
}

.changelog-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.changelog-title {
  font-weight: 600;
  font-size: 14px;
  color: #f1f5f9;
}

.changelog-list {
  margin: 0;
  padding-left: 18px;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.8;
}

.admin-main {
  padding: 30px 40px;
  max-width: 1400px;
  margin: 0 auto;
  background: #0f172a;
}

/* Arbore品牌Tabs样式 */
.arbore-tabs {
  background: rgba(15, 23, 42, 0.5);
  border-radius: 8px;
  padding: 20px;
}

.arbore-tabs :deep(.el-tabs__header) {
  margin-bottom: 20px;
}

.arbore-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: rgba(148, 163, 184, 0.1);
}

.arbore-tabs :deep(.el-tabs__item) {
  color: #94a3b8;
  font-weight: 500;
}

.arbore-tabs :deep(.el-tabs__item.is-active) {
  color: #10b981;
}

.arbore-tabs :deep(.el-tabs__active-bar) {
  background-color: #10b981;
}

.arbore-tabs :deep(.el-tabs__item:hover) {
  color: #10b981;
}
</style>

