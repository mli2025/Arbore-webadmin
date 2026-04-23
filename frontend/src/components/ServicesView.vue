<template>
  <!--
    服务状态视图 / Services View

    中文说明：
    本组件负责集中展示 Arbore AI Host 平台中各个核心服务（Docker 容器或 systemd
    服务）的运行状态、健康检查结果以及常用操作入口。页面上的每一个卡片都对应
    一个逻辑服务实例，支持一键启动、停止、重启以及跳转到 Web 控制台等动作。

    English description:
    This view aggregates the runtime state of all core services that make up
    the Arbore AI Host platform.  Each card represents either a Docker
    container based service or a systemd unit and exposes shortcuts to open
    its web UI (if any), as well as start/stop/restart controls.

    设计关注点 / Design considerations:
    - 清晰的状态标识：同时展示原始状态字段和翻译后的中文文案，避免误解。
    - 许可证联动：当许可证无效时，禁止标准服务的启停操作，并在顶部给出提示。
    - 可扩展配置：服务的展示名称与访问 URL 抽离到 serviceConfig 中，方便后续
      增减服务或更换端口时只修改配置而无需调整模板结构。
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
    <el-row :gutter="20">
      <el-col :span="8" v-for="service in services" :key="service.name">
        <el-card class="service-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="service-name">{{ getServiceDisplayName(service.name) }}</span>
              <el-tag :type="getStatusType(service.status)" size="small">
                {{ getStatusText(service.status) }}
              </el-tag>
            </div>
          </template>
          
          <div class="service-info">
            <p><strong>状态:</strong> {{ service.status }}</p>
            <p v-if="service.health !== 'unknown'">
              <strong>健康:</strong> 
              <el-tag :type="service.health === 'healthy' ? 'success' : 'warning'" size="small">
                {{ service.health }}
              </el-tag>
            </p>
            <p v-if="service.ports.length > 0">
              <strong>端口:</strong> {{ service.ports.join(', ') }}
            </p>
            <p v-if="service.type === 'systemd'">
              <strong>类型:</strong> <el-tag size="small">Systemd</el-tag>
            </p>
            
            <div class="service-actions" style="margin-top: 10px;">
              <el-button 
                type="primary" 
                size="small" 
                @click="openService(service)"
                :disabled="service.status !== 'running'"
                style="margin-right: 5px;"
              >
                访问服务
              </el-button>
              
              <el-button 
                v-if="service.status !== 'running' && (service.type === 'systemd' || service.name.startsWith('service-'))"
                type="success" 
                size="small" 
                @click="startService(service)"
                :loading="service.loading"
                :disabled="!licenseValid"
                style="margin-right: 5px;"
              >
                启动
              </el-button>
              
              <el-button 
                v-if="service.status === 'running' && (service.type === 'systemd' || service.name.startsWith('service-'))"
                type="warning" 
                size="small" 
                @click="stopService(service)"
                :loading="service.loading"
                style="margin-right: 5px;"
              >
                停止
              </el-button>
              
              <el-button 
                v-if="service.status === 'running' && (service.type === 'systemd' || service.name.startsWith('service-'))"
                type="info" 
                size="small" 
                @click="restartService(service)"
                :loading="service.loading"
                :disabled="!licenseValid"
              >
                重启
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <el-button 
      type="primary" 
      @click="refreshServices" 
      :loading="loading"
      style="margin-top: 20px;"
    >
      刷新状态
    </el-button>
  </div>
</template>

<script setup>
// 服务状态视图逻辑层（script 部分）
// Script section for the Services View component.
// 这里主要完成三类工作：
// 1) 与后端 /api/v1/services API 交互，获取当前服务状态及许可证校验结果；
// 2) 根据状态信息推导出标签颜色、文案等展示细节；
// 3) 封装对单个服务的启动 / 停止 / 重启等操作，统一处理错误提示。

import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const services = ref([])
const loading = ref(false)
const licenseValid = ref(true)
const licenseErrorCode = ref(null)

// 获取当前服务器 IP（从浏览器访问地址中推导）
// Get current server IP from window.location, so that the same前端
// 页面可以在不同部署环境下自动适配后端主机地址。
const getServerIP = () => {
  return window.location.hostname
}

// 获取当前协议（与页面一致，支持 HTTP/HTTPS 自动切换）
const getBaseUrl = () => {
  return `${window.location.protocol}//${getServerIP()}`
}

// 服务展示配置（Service display configuration）
// key 为后端返回的服务名称，value 中包含中文展示名和可选的 Web 访问地址。
// 此处故意保持为一个集中配置块，方便在软件著作权文档中说明各个子系统作用。
const serviceConfig = {
  'arbore-flow': { name: '工作流服务', url: () => `${getBaseUrl()}:5678` },
  'arbore-func': { name: '应用服务', url: () => `${getBaseUrl()}:13000` },
  'arbore-postgres-nocobase': { name: 'PostgreSQL (应用数据库)', url: null },
  'arbore-postgres-vector': { name: 'PostgreSQL (向量数据库)', url: null },
  'arbore-ollama': { name: 'AI模型服务', url: () => `${getBaseUrl()}:11434` },
  'arbore-ollama-webui': { name: 'AI模型界面', url: () => `${getBaseUrl()}:3000` },
  'kanban-frontend': { name: '看板前端服务', url: () => `${getBaseUrl()}:13050` },
  'kanban-backend': { name: '看板后端服务', url: () => `${getBaseUrl()}:13051` },
}

const getServiceDisplayName = (name) => {
  return serviceConfig[name]?.name || name
}

const getStatusType = (status) => {
  const statusMap = {
    'running': 'success',
    'stopped': 'danger',
    'exited': 'danger',
    'restarting': 'warning',
    'not_found': 'info',
    'unknown': 'info'
  }
  return statusMap[status] || 'info'
}

const getStatusText = (status) => {
  const statusMap = {
    'running': '运行中',
    'stopped': '已停止',
    'exited': '已停止',
    'restarting': '重启中',
    'not_found': '未找到',
    'unknown': '未知'
  }
  return statusMap[status] || status
}

const openService = (service) => {
  const config = serviceConfig[service.name]
  if (config && config.url) {
    // 如果url是函数，调用它获取URL
    const url = typeof config.url === 'function' ? config.url() : config.url
    try {
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch (error) {
      ElMessage.error('无法打开服务地址: ' + error.message)
      // 如果弹窗被阻止，尝试直接跳转
      window.location.href = url
    }
  } else {
    ElMessage.info('该服务没有Web访问地址')
  }
}

const refreshServices = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/v1/services')
    services.value = (response.data.services || []).map(service => ({
      ...service,
      loading: false
    }))
    licenseValid.value = response.data.licenseValid !== false
    licenseErrorCode.value = response.data.licenseErrorCode || null
    ElMessage.success('服务状态已更新')
  } catch (error) {
    ElMessage.error('获取服务状态失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const startService = async (service) => {
  if (!licenseValid.value) {
    ElMessage.warning('请先完成许可证注册')
    return
  }
  service.loading = true
  try {
    const response = await axios.post(`/api/v1/services/${service.name}/start`)
    ElMessage.success(response.data.message || '服务启动成功')
    await refreshServices()
  } catch (error) {
    ElMessage.error('启动服务失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    service.loading = false
  }
}

const stopService = async (service) => {
  service.loading = true
  try {
    const response = await axios.post(`/api/v1/services/${service.name}/stop`)
    ElMessage.success(response.data.message || '服务停止成功')
    await refreshServices()
  } catch (error) {
    ElMessage.error('停止服务失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    service.loading = false
  }
}

const restartService = async (service) => {
  if (!licenseValid.value) {
    ElMessage.warning('请先完成许可证注册')
    return
  }
  service.loading = true
  try {
    const response = await axios.post(`/api/v1/services/${service.name}/restart`)
    ElMessage.success(response.data.message || '服务重启成功')
    await refreshServices()
  } catch (error) {
    ElMessage.error('重启服务失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    service.loading = false
  }
}

onMounted(() => {
  refreshServices()
  // 每30秒自动刷新
  setInterval(refreshServices, 30000)
})
</script>

<style scoped>
.services-view {
  padding: 20px 0;
}

.service-card {
  margin-bottom: 20px;
  height: 100%;
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 8px;
}

.service-card :deep(.el-card__header) {
  background: rgba(15, 23, 42, 0.5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  color: #f1f5f9;
}

.service-card :deep(.el-card__body) {
  background: rgba(30, 41, 59, 0.3);
  color: #f1f5f9;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.service-name {
  font-weight: 600;
  font-size: 16px;
  color: #f1f5f9;
}

.service-info p {
  margin: 8px 0;
  font-size: 14px;
  color: #94a3b8;
}

.service-info p strong {
  color: #f1f5f9;
}

.license-alert {
  margin-bottom: 20px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
}
</style>

