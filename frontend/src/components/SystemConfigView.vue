<template>
  <!--
    系统配置视图 / System Configuration View
    UI 文案使用英文。注释保留中文。
  -->
  <div class="system-config-view">
    <div class="page-header">
      <div class="header-title">
        <h2>system</h2>
        <p class="header-desc">
          Server IP and OTA update configuration. These values feed into
          Nginx, business APIs and the updater.
        </p>
      </div>
    </div>

    <el-card class="config-card" shadow="never">
      <template #header>
        <span class="card-title">server ip</span>
      </template>

      <div class="ip-info-section">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="current ip">
            <el-tag type="info" size="default">{{ ipInfo.current_ip || 'detecting...' }}</el-tag>
            <el-button
              type="primary"
              size="small"
              @click="refreshIpInfo"
              :loading="loading"
              style="margin-left: 10px;"
            >
              <el-icon><Refresh /></el-icon>
              refresh
            </el-button>
          </el-descriptions-item>

          <el-descriptions-item label="configured ip">
            <el-tag
              :type="ipInfo.needs_update ? 'warning' : 'success'"
              size="default"
            >
              {{ ipInfo.configured_ip || 'not configured' }}
            </el-tag>
          </el-descriptions-item>

          <el-descriptions-item label="status">
            <el-alert v-if="ipInfo.needs_update" type="warning" :closable="false" show-icon>
              <template #title>
                <strong>ip mismatch</strong>
                <p style="margin: 5px 0 0 0; font-size: 12px;">
                  current ip ({{ ipInfo.current_ip }}) differs from configured ip ({{ ipInfo.configured_ip }})
                </p>
              </template>
            </el-alert>
            <el-alert v-else-if="ipInfo.configured_ip" type="success" :closable="false" show-icon>
              <template #title>
                <strong>ip configured correctly</strong>
                <p style="margin: 5px 0 0 0; font-size: 12px;">
                  current and configured ip are aligned
                </p>
              </template>
            </el-alert>
            <el-alert v-else type="info" :closable="false" show-icon>
              <template #title>
                <strong>first-time setup</strong>
                <p style="margin: 5px 0 0 0; font-size: 12px;">
                  click the button below to persist the current ip
                </p>
              </template>
            </el-alert>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="action-section">
        <el-button
          type="primary"
          @click="updateIp"
          :loading="updating"
          :disabled="!ipInfo.needs_update && ipInfo.configured_ip !== ''"
        >
          <el-icon><Setting /></el-icon>
          {{ ipInfo.configured_ip ? 'update ip' : 'save current ip' }}
        </el-button>

        <el-button
          @click="refreshIpInfo"
          :loading="loading"
          style="margin-left: 10px;"
        >
          <el-icon><Refresh /></el-icon>
          refresh
        </el-button>
      </div>

      <!-- 更新结果展示 -->
      <el-card v-if="updateResult" class="result-card" shadow="never" style="margin-top: 16px;">
        <template #header>
          <div class="result-header">
            <el-icon :class="updateResult.success ? 'success-icon' : 'error-icon'">
              <component :is="updateResult.success ? 'CircleCheck' : 'CircleClose'" />
            </el-icon>
            <span>{{ updateResult.success ? 'update succeeded' : 'update failed' }}</span>
          </div>
        </template>

        <div class="result-content">
          <p><strong>new ip:</strong> {{ updateResult.new_ip }}</p>
          <p v-if="updateResult.message"><strong>message:</strong> {{ updateResult.message }}</p>

          <div v-if="updateResult.restart_results && updateResult.restart_results.length > 0" style="margin-top: 12px;">
            <p><strong>service restart:</strong></p>
            <ul style="margin-left: 20px;">
              <li v-for="(result, index) in updateResult.restart_results" :key="index">
                {{ result.service }}:
                <el-tag
                  :type="result.status === 'restarted' ? 'success' : 'danger'"
                  size="small"
                >
                  {{ result.status }}
                </el-tag>
                <span v-if="result.error" style="color: var(--mocha-red); margin-left: 10px;">
                  {{ result.error }}
                </span>
              </li>
            </ul>
          </div>

          <div v-if="updateResult.script_output" style="margin-top: 12px;">
            <p><strong>script output:</strong></p>
            <pre class="script-output">{{ updateResult.script_output }}</pre>
          </div>
        </div>
      </el-card>
    </el-card>

    <!-- OTA configuration -->
    <el-card class="config-card" shadow="never" style="margin-top: 16px;">
      <template #header>
        <span class="card-title">ota update</span>
      </template>
      <el-form label-width="160px" label-position="left">
        <el-form-item label="update server url">
          <el-input
            v-model="otaUrl"
            placeholder="https://your-server.com/arbore-updates"
            clearable
            style="max-width: 500px;"
          />
          <div class="form-hint">
            the server must host version.json, frontend-dist.tar.gz, backend.tar.gz
          </div>
        </el-form-item>
        <el-form-item label="auto check">
          <el-switch v-model="otaEnabled" />
          <span class="form-hint" style="margin-left: 8px;">check for new versions hourly when enabled</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveOtaConfig" :loading="otaSaving">save</el-button>
          <el-button @click="checkUpdateNow" :loading="otaChecking" :disabled="!otaUrl">check now</el-button>
        </el-form-item>
        <el-form-item v-if="otaCheckResult" label="check result">
          <el-tag v-if="otaCheckResult.has_update" type="warning">
            new version available: v{{ otaCheckResult.remote_version }}
          </el-tag>
          <el-tag v-else-if="otaCheckResult.error" type="danger">
            check failed: {{ otaCheckResult.error }}
          </el-tag>
          <el-tag v-else type="success">
            up to date (v{{ otaCheckResult.current_version }})
          </el-tag>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
// 系统配置逻辑（System configuration logic）
// 1) refreshIpInfo: 读取检测到的服务器 IP 与已保存配置；
// 2) updateIp:      用户确认后写入配置并重启相关服务；
// 3) updateResult:  向用户反馈脚本结果与各服务重启状态。
import { ref, onMounted, onBeforeUnmount, inject } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Setting, CircleCheck, CircleClose } from '@element-plus/icons-vue'

const TAB_NAME = 'system'

const ipInfo = ref({
  current_ip: '',
  configured_ip: '',
  needs_update: false,
})

const loading = ref(false)
const updating = ref(false)
const updateResult = ref(null)

const otaUrl = ref('')
const otaEnabled = ref(false)
const otaSaving = ref(false)
const otaChecking = ref(false)
const otaCheckResult = ref(null)

const refreshIpInfo = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/v1/system/config')
    ipInfo.value = {
      current_ip: response.data.current_ip || '',
      configured_ip: response.data.configured_ip || '',
      needs_update: response.data.needs_update || false,
    }
  } catch (error) {
    ElMessage.error('failed to fetch ip info: ' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

const updateIp = async () => {
  try {
    await ElMessageBox.confirm(
      `update the configured server ip to ${ipInfo.value.current_ip}?\n\nthis will:\n1. update SERVER_IP in .env\n2. update nginx, chat-service and other config files\n3. restart arbore-flow and arbore-nginx`,
      'confirm ip update',
      {
        confirmButtonText: 'confirm',
        cancelButtonText: 'cancel',
        type: 'warning',
      },
    )
    updating.value = true
    updateResult.value = null
    try {
      const response = await axios.post('/api/v1/system/config/update-ip')
      updateResult.value = response.data
      if (response.data.success) {
        ElMessage.success(response.data.message || 'ip configuration updated')
        await refreshIpInfo()
      } else {
        ElMessage.error('ip update failed')
      }
    } catch (error) {
      const errorDetail = error.response?.data?.detail || error.message
      updateResult.value = { success: false, error: errorDetail }
      ElMessage.error('ip update failed: ' + errorDetail)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('operation failed: ' + (error.message || error))
    }
  } finally {
    updating.value = false
  }
}

const loadOtaConfig = async () => {
  try {
    const res = await axios.get('/admin-api/api/v1/update/config')
    otaUrl.value = res.data.update_url || ''
    otaEnabled.value = res.data.enabled || false
  } catch (e) {
    console.error('Failed to load OTA config:', e)
  }
}

const saveOtaConfig = async () => {
  otaSaving.value = true
  try {
    const formData = new FormData()
    formData.append('update_url', otaUrl.value)
    formData.append('enabled', otaEnabled.value)
    await axios.post('/admin-api/api/v1/update/config', formData)
    ElMessage.success('saved')
  } catch (e) {
    ElMessage.error('save failed: ' + (e.response?.data?.detail || e.message))
  } finally {
    otaSaving.value = false
  }
}

const checkUpdateNow = async () => {
  otaChecking.value = true
  otaCheckResult.value = null
  try {
    await saveOtaConfig()
    const res = await axios.get('/admin-api/api/v1/update/check?force=true')
    otaCheckResult.value = res.data
  } catch (e) {
    otaCheckResult.value = { error: e.response?.data?.detail || e.message }
  } finally {
    otaChecking.value = false
  }
}

const refreshAll = async () => {
  await refreshIpInfo()
  await loadOtaConfig()
}

const registerRefresh   = inject('registerRefresh',   null)
const unregisterRefresh = inject('unregisterRefresh', null)

onMounted(() => {
  refreshAll()
  if (registerRefresh) registerRefresh(TAB_NAME, refreshAll)
})
onBeforeUnmount(() => {
  if (unregisterRefresh) unregisterRefresh(TAB_NAME)
})
</script>

<style scoped>
.system-config-view {
  padding: 0;
  font-family: var(--font-mono);
  color: var(--fg-text);
}

.page-header {
  margin-bottom: 16px;
  padding: 4px 0 12px;
  border-bottom: 1px solid var(--border);
}
.header-title h2 {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg-text);
  margin: 0 0 4px 0;
  text-transform: lowercase;
  letter-spacing: 1.5px;
}
.header-title h2::before {
  content: '┃ ';
  color: var(--accent);
}
.header-desc {
  font-size: 12px;
  color: var(--fg-muted);
  margin: 0;
}

.config-card { margin-bottom: 14px; }

.system-config-view :deep(.el-card__header) {
  padding: 10px 14px;
}
.card-title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--accent);
  font-weight: 600;
}

.ip-info-section { margin-bottom: 16px; }
.ip-info-section :deep(.el-descriptions__label) {
  background: var(--bg-base);
  color: var(--fg-muted);
  border-color: var(--border);
  font-weight: 500;
  text-transform: lowercase;
  font-size: 12px;
}
.ip-info-section :deep(.el-descriptions__content) {
  color: var(--fg-text);
  border-color: var(--border);
  font-size: 12.5px;
}

.action-section {
  display: flex;
  gap: 4px;
  align-items: center;
}

.result-card { background: var(--bg-mantle); }

.result-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--fg-text);
  font-size: 12.5px;
  text-transform: lowercase;
}

.success-icon { color: var(--mocha-green); }
.error-icon   { color: var(--mocha-red); }

.result-content { color: var(--fg-subtext); font-size: 12.5px; }
.result-content p { margin: 6px 0; }
.result-content strong { color: var(--fg-text); }
.result-content ul { margin: 8px 0; }
.result-content li { margin: 4px 0; }

.script-output {
  background: var(--bg-crust);
  border: 1px solid var(--border);
  border-radius: var(--radius-tile);
  padding: 12px 14px;
  color: var(--fg-subtext);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.55;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 300px;
  overflow-y: auto;
  margin: 0;
}

.form-hint {
  font-size: 11.5px;
  color: var(--fg-muted);
  margin-top: 4px;
}

.system-config-view :deep(.el-form-item__label) {
  color: var(--fg-muted);
  font-family: var(--font-mono);
  text-transform: lowercase;
  font-size: 12.5px;
}
</style>
