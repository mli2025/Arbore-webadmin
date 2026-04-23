<template>
  <!--
    系统资源监控视图 / System Resources View

    中文说明：
    本组件通过调用后端 /api/v1/system/resources 接口，定期获取 CPU、内存、
    磁盘等关键资源的使用情况，并以进度条的方式进行可视化展示。该页面主要
    面向运维人员，用于快速判断当前宿主机是否存在资源瓶颈。

    English description:
    This component periodically polls the `/api/v1/system/resources` endpoint
    to retrieve CPU, memory and disk utilization metrics of the host machine.
    The data is rendered as progress bars so that operators can quickly spot
    abnormal resource consumption patterns (for example memory exhaustion or
    disk almost full).
  -->
  <div class="resources-view">
    <el-row :gutter="20">
      <el-col :span="24">
        <el-card shadow="hover" class="resource-card">
          <template #header>
            <span>CPU使用率</span>
          </template>
          <div class="resource-item">
            <el-progress 
              :percentage="resources.cpu.percent" 
              :color="getColor(resources.cpu.percent)"
              :stroke-width="20"
            />
            <p style="margin-top: 10px;">
              核心数: {{ resources.cpu.count }}
            </p>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="24">
        <el-card shadow="hover" class="resource-card">
          <template #header>
            <span>内存使用</span>
          </template>
          <div class="resource-item">
            <el-progress 
              :percentage="resources.memory.percent" 
              :color="getColor(resources.memory.percent)"
              :stroke-width="20"
            />
            <p style="margin-top: 10px;">
              已用: {{ formatBytes(resources.memory.used) }} / 
              {{ formatBytes(resources.memory.total) }}
            </p>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="24">
        <el-card shadow="hover" class="resource-card">
          <template #header>
            <span>磁盘使用</span>
          </template>
          <div class="resource-item">
            <el-progress 
              :percentage="resources.disk.percent" 
              :color="getColor(resources.disk.percent)"
              :stroke-width="20"
            />
            <p style="margin-top: 10px;">
              已用: {{ formatBytes(resources.disk.used) }} / 
              {{ formatBytes(resources.disk.total) }}
            </p>
          </div>
        </el-card>
      </el-col>

      <template v-if="resources.gpu && resources.gpu.length">
        <el-col :span="24" v-for="gpu in resources.gpu" :key="gpu.index">
          <el-card shadow="hover" class="resource-card">
            <template #header>
              <span>GPU {{ gpu.index }}: {{ gpu.name }}</span>
            </template>
            <div class="resource-item">
              <p class="resource-label">算力使用率</p>
              <el-progress 
                :percentage="gpu.utilization_percent" 
                :color="getColor(gpu.utilization_percent)"
                :stroke-width="16"
              />
              <p class="resource-label" style="margin-top: 14px;">显存使用</p>
              <el-progress 
                :percentage="gpu.memory_percent" 
                :color="getColor(gpu.memory_percent)"
                :stroke-width="16"
              />
              <p style="margin-top: 10px;">
                已用: {{ formatBytes(gpu.memory_used) }} / {{ formatBytes(gpu.memory_total) }}
              </p>
            </div>
          </el-card>
        </el-col>
      </template>
    </el-row>
    
    <el-button 
      type="primary" 
      @click="refreshResources" 
      :loading="loading"
      style="margin-top: 20px;"
    >
      刷新资源
    </el-button>
  </div>
</template>

<script setup>
// 资源监控逻辑（Resource monitoring logic）
// 职责说明：
// 1) 定期从后端拉取最新资源使用情况；
// 2) 将原始字节数转换为人类可读的单位字符串；
// 3) 根据占用百分比返回对应的颜色，形成直观的风险感知。
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const resources = ref({
  cpu: { percent: 0, count: 0 },
  memory: { total: 0, used: 0, percent: 0 },
  disk: { total: 0, used: 0, percent: 0 },
  gpu: []
})
const loading = ref(false)

// 根据占比返回进度条颜色（绿 / 橙 / 红）
// Map percentage to progress-bar color (green / orange / red).
const getColor = (percent) => {
  if (percent < 50) return '#10b981'  // Arbore品牌绿色
  if (percent < 80) return '#f59e0b'  // 橙色警告
  return '#ef4444'  // 红色危险
}

const formatBytes = (bytes) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}

const refreshResources = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/v1/system/resources')
    resources.value = response.data
  } catch (error) {
    ElMessage.error('获取系统资源失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  refreshResources()
  // 每10秒自动刷新
  setInterval(refreshResources, 10000)
})
</script>

<style scoped>
.resources-view {
  padding: 20px 0;
}

.resources-view :deep(.el-card) {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 8px;
}

.resources-view :deep(.el-card__header) {
  background: rgba(15, 23, 42, 0.5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  color: #f1f5f9;
}

.resources-view :deep(.el-card__body) {
  background: rgba(30, 41, 59, 0.3);
  color: #f1f5f9;
}

.resource-card {
  margin-bottom: 20px;
}

.resource-item {
  padding: 10px 0;
}

.resource-item p {
  color: #94a3b8;
  margin-top: 10px;
}

.resource-label {
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 6px;
}
</style>

