<template>
  <!--
    日志查看视图 / Logs View

    中文说明：
    本组件为运维人员提供统一的日志入口，可以在浏览器中直接查看 Web Admin
    控制台自身日志以及各个业务服务的容器日志，从而在不登录服务器的情况下
    完成大多数日常排障工作。

    English description:
    This view lets operators inspect logs produced by the web‑admin backend
    service itself as well as logs from individual business services
    (Docker containers).  It is intentionally simple but powerful enough
    for first‑line troubleshooting without SSH access.
  -->
  <div class="logs-view">
    <!-- 控制台服务（Web Admin API）自身日志 -->
    <el-card class="log-section-card" shadow="never">
      <template #header>
        <span>控制台服务日志（Web Admin API）</span>
      </template>
      <p class="section-desc">查看本管理控制台后端的运行日志，便于排查问题。</p>
      <el-button type="primary" @click="loadAdminLogs" :loading="loadingAdmin">
        加载控制台日志
      </el-button>
    </el-card>

    <el-form :inline="true" class="logs-form">
      <el-form-item label="选择服务">
        <el-select
          v-model="selectedService"
          placeholder="请选择服务"
          style="width: 200px;"
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
      
      <el-form-item label="日志行数">
        <el-input-number v-model="tail" :min="10" :max="1000" :step="10" />
      </el-form-item>
      
      <el-form-item>
        <el-button type="primary" @click="loadLogs" :loading="loading">
          加载日志
        </el-button>
      </el-form-item>
    </el-form>
    
    <el-card v-if="logs.length > 0" class="log-display-card">
      <template #header>
        <span>{{ logSourceLabel }}</span>
      </template>
      <el-scrollbar height="500px">
        <pre class="log-content">{{ (logs || []).join('\n') }}</pre>
      </el-scrollbar>
    </el-card>
    
    <el-empty v-else description="请选择上方「控制台服务」或业务服务并点击加载日志" />
  </div>
</template>

<script setup>
// 日志查看逻辑（Log viewing logic）
// - fetchServiceList: 与服务状态页复用后端数据，动态获得服务名称列表；
// - loadAdminLogs: 加载控制台后端自身的日志文件，方便排查 API 问题；
// - loadLogs:      按照用户选择的服务名获取对应容器的最新日志片段。
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const selectedService = ref('arbore-flow')
const tail = ref(100)
const logs = ref([])
const loading = ref(false)
const loadingAdmin = ref(false)
const serviceList = ref([])
const loadingServices = ref(false)
const logSource = ref('') // 'admin' | 'service'
const logSourceLabel = computed(() =>
  logSource.value === 'admin' ? '控制台服务日志' : (logSource.value === 'service' && selectedService.value ? `${selectedService.value} 日志` : '日志')
)

// 从后端 /api/v1/services 拉取服务列表，与「服务状态」一致，避免硬编码遗漏（如 quickchart）
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
    console.error('获取服务列表失败:', e)
    serviceList.value = []
  } finally {
    loadingServices.value = false
  }
}

onMounted(() => {
  fetchServiceList()
})

const loadAdminLogs = async () => {
  loadingAdmin.value = true
  try {
    const response = await axios.get('/api/v1/system/admin-logs', {
      params: { tail: 200 }
    })
    logs.value = Array.isArray(response.data?.logs) ? response.data.logs : []
    logSource.value = 'admin'
    ElMessage.success('控制台日志加载成功')
  } catch (error) {
    ElMessage.error('加载控制台日志失败: ' + error.message)
    logs.value = []
  } finally {
    loadingAdmin.value = false
  }
}

const loadLogs = async () => {
  if (!selectedService.value) {
    ElMessage.warning('请先选择服务')
    return
  }
  
  loading.value = true
  try {
    const response = await axios.get(`/api/v1/services/${selectedService.value}/logs`, {
      params: { tail: tail.value }
    })
    logs.value = Array.isArray(response.data?.logs) ? response.data.logs : []
    logSource.value = 'service'
    ElMessage.success('日志加载成功')
  } catch (error) {
    ElMessage.error('加载日志失败: ' + error.message)
    logs.value = []
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.logs-view {
  padding: 20px 0;
}

.log-section-card {
  margin-bottom: 20px;
}
.section-desc {
  color: #94a3b8;
  font-size: 12px;
  margin: 0 0 12px 0;
}
.logs-form {
  margin-bottom: 20px;
}
.log-display-card {
  margin-top: 12px;
}

.logs-view :deep(.el-card) {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 8px;
}

.logs-view :deep(.el-card__body) {
  background: rgba(15, 23, 42, 0.5);
}

.log-content {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #10b981;
  background: #0f172a;
  padding: 15px;
  border-radius: 4px;
  white-space: pre-wrap;
  word-wrap: break-word;
  border: 1px solid rgba(148, 163, 184, 0.1);
}
</style>

