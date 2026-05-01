<template>
  <!--
    日志查看视图 / Logs View
    UI 文案使用英文。注释保留中文。
  -->
  <div class="logs-view">
    <div class="page-header">
      <div class="header-title">
        <h2>logs</h2>
        <p class="header-desc">
          Inspect web-admin backend logs and per-service container logs
          without SSH access to the host.
        </p>
      </div>
    </div>

    <!-- Web Admin API self log -->
    <el-card class="log-section-card" shadow="never">
      <template #header>
        <span class="card-title">web admin api log</span>
      </template>
      <p class="section-desc">tail the web-admin-api process log to debug api errors.</p>
      <el-button type="primary" @click="loadAdminLogs" :loading="loadingAdmin">
        load admin log
      </el-button>
    </el-card>

    <!-- Service container log -->
    <el-card class="log-section-card" shadow="never">
      <template #header>
        <span class="card-title">service container log</span>
      </template>
      <el-form :inline="true" class="logs-form">
        <el-form-item label="service">
          <el-select
            v-model="selectedService"
            placeholder="select a service"
            style="width: 240px;"
            :loading="loadingServices"
            filterable
          >
            <el-option
              v-for="service in serviceList"
              :key="service"
              :label="service"
              :value="service"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="tail">
          <el-input-number v-model="tail" :min="10" :max="1000" :step="10" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="loadLogs" :loading="loading">
            load
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="logs.length > 0" class="log-display-card" shadow="never">
      <template #header>
        <span class="card-title">{{ logSourceLabel }}</span>
        <span class="text-muted">{{ logs.length }} lines</span>
      </template>
      <el-scrollbar height="500px">
        <pre class="log-content">{{ (logs || []).join('\n') }}</pre>
      </el-scrollbar>
    </el-card>

    <el-empty v-else description="select a source above and click load to view logs" />
  </div>
</template>

<script setup>
// 日志查看逻辑（Log viewing logic）
// - fetchServiceList: 与服务状态页复用后端数据，动态获得服务名称列表；
// - loadAdminLogs:    加载 web-admin-api 自身的日志文件
// - loadLogs:         加载选定容器的最新日志
import { ref, computed, onMounted, onBeforeUnmount, inject } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const TAB_NAME = 'logs'
const selectedService = ref('arbore-flow')
const tail = ref(100)
const logs = ref([])
const loading = ref(false)
const loadingAdmin = ref(false)
const serviceList = ref([])
const loadingServices = ref(false)
const logSource = ref('') // 'admin' | 'service'
const logSourceLabel = computed(() => {
  if (logSource.value === 'admin') return 'web admin api log'
  if (logSource.value === 'service' && selectedService.value) {
    return `${selectedService.value} log`
  }
  return 'log'
})

const fetchServiceList = async () => {
  loadingServices.value = true
  try {
    const res = await axios.get('/api/v1/services')
    const list = (res.data?.services || []).map(s => s.name).filter(Boolean)
    if (list.length) {
      serviceList.value = list
      if (!list.includes(selectedService.value)) {
        selectedService.value = list[0]
      }
    }
  } catch (e) {
    console.error('failed to fetch service list:', e)
    serviceList.value = []
  } finally {
    loadingServices.value = false
  }
}

const loadAdminLogs = async () => {
  loadingAdmin.value = true
  try {
    const response = await axios.get('/api/v1/system/admin-logs', {
      params: { tail: 200 },
    })
    logs.value = Array.isArray(response.data?.logs) ? response.data.logs : []
    logSource.value = 'admin'
    ElMessage.success('admin log loaded')
  } catch (error) {
    ElMessage.error('load admin log failed: ' + error.message)
    logs.value = []
  } finally {
    loadingAdmin.value = false
  }
}

const loadLogs = async () => {
  if (!selectedService.value) {
    ElMessage.warning('select a service first')
    return
  }
  loading.value = true
  try {
    const response = await axios.get(`/api/v1/services/${selectedService.value}/logs`, {
      params: { tail: tail.value },
    })
    logs.value = Array.isArray(response.data?.logs) ? response.data.logs : []
    logSource.value = 'service'
    ElMessage.success('log loaded')
  } catch (error) {
    ElMessage.error('load log failed: ' + error.message)
    logs.value = []
  } finally {
    loading.value = false
  }
}

const refreshActive = () => {
  if (logSource.value === 'admin') return loadAdminLogs()
  if (logSource.value === 'service') return loadLogs()
  return fetchServiceList()
}

const registerRefresh   = inject('registerRefresh',   null)
const unregisterRefresh = inject('unregisterRefresh', null)

onMounted(() => {
  fetchServiceList()
  if (registerRefresh) registerRefresh(TAB_NAME, refreshActive)
})
onBeforeUnmount(() => {
  if (unregisterRefresh) unregisterRefresh(TAB_NAME)
})
</script>

<style scoped>
.logs-view {
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

.card-title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--accent);
  font-weight: 600;
}
.logs-view :deep(.el-card__header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
}

.log-section-card { margin-bottom: 14px; }
.section-desc {
  color: var(--fg-muted);
  font-size: 12px;
  margin: 0 0 12px 0;
}
.logs-form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.logs-form :deep(.el-form-item__label) {
  color: var(--fg-muted);
  font-family: var(--font-mono);
  text-transform: lowercase;
  font-size: 12px;
}
.log-display-card { margin-top: 4px; }

.log-content {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  color: var(--mocha-green);
  background: var(--bg-crust);
  padding: 12px 14px;
  border-radius: var(--radius-tile);
  white-space: pre-wrap;
  word-wrap: break-word;
  border: 1px solid var(--border);
  margin: 0;
}
</style>
