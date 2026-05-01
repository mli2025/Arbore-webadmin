<template>
  <!--
    系统资源监控视图 / System Resources View
    UI 文案使用英文。脚本注释保留中文。
  -->
  <div class="resources-view">
    <div class="page-header">
      <div class="header-title">
        <h2>resources</h2>
        <p class="header-desc">
          Live CPU / memory / disk / GPU utilisation, polled every 10s.
        </p>
      </div>
      <button class="tui-btn-mono" :class="{ loading }" @click="refreshResources">
        refresh
      </button>
    </div>

    <el-row :gutter="20">
      <el-col :span="24">
        <el-card shadow="never" class="resource-card">
          <template #header>
            <span class="rc-title">cpu</span>
            <span class="rc-meta">{{ resources.cpu.percent }}% · cores {{ resources.cpu.count }}</span>
          </template>
          <el-progress
            :percentage="resources.cpu.percent"
            :color="getColor(resources.cpu.percent)"
            :stroke-width="14"
          />
        </el-card>
      </el-col>

      <el-col :span="24">
        <el-card shadow="never" class="resource-card">
          <template #header>
            <span class="rc-title">memory</span>
            <span class="rc-meta">
              {{ resources.memory.percent }}% ·
              {{ formatBytes(resources.memory.used) }} /
              {{ formatBytes(resources.memory.total) }}
            </span>
          </template>
          <el-progress
            :percentage="resources.memory.percent"
            :color="getColor(resources.memory.percent)"
            :stroke-width="14"
          />
        </el-card>
      </el-col>

      <el-col :span="24">
        <el-card shadow="never" class="resource-card">
          <template #header>
            <span class="rc-title">disk</span>
            <span class="rc-meta">
              {{ resources.disk.percent }}% ·
              {{ formatBytes(resources.disk.used) }} /
              {{ formatBytes(resources.disk.total) }}
            </span>
          </template>
          <el-progress
            :percentage="resources.disk.percent"
            :color="getColor(resources.disk.percent)"
            :stroke-width="14"
          />
        </el-card>
      </el-col>

      <template v-if="resources.gpu && resources.gpu.length">
        <el-col :span="24" v-for="gpu in resources.gpu" :key="gpu.index">
          <el-card shadow="never" class="resource-card">
            <template #header>
              <span class="rc-title">gpu {{ gpu.index }}</span>
              <span class="rc-meta">{{ gpu.name }}</span>
            </template>
            <p class="resource-label">utilisation · {{ gpu.utilization_percent }}%</p>
            <el-progress
              :percentage="gpu.utilization_percent"
              :color="getColor(gpu.utilization_percent)"
              :stroke-width="12"
            />
            <p class="resource-label" style="margin-top: 14px;">
              memory · {{ gpu.memory_percent }}% ·
              {{ formatBytes(gpu.memory_used) }} / {{ formatBytes(gpu.memory_total) }}
            </p>
            <el-progress
              :percentage="gpu.memory_percent"
              :color="getColor(gpu.memory_percent)"
              :stroke-width="12"
            />
          </el-card>
        </el-col>
      </template>
    </el-row>
  </div>
</template>

<script setup>
// 资源监控逻辑（Resource monitoring logic）
// 1) 定期从后端拉取最新资源使用情况；
// 2) 字节数转换为人类可读字符串；
// 3) 占用百分比对应到 mocha 主题颜色（green / peach / red）。
import { ref, onMounted, onBeforeUnmount, inject } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const TAB_NAME = 'resources'
const resources = ref({
  cpu: { percent: 0, count: 0 },
  memory: { total: 0, used: 0, percent: 0 },
  disk: { total: 0, used: 0, percent: 0 },
  gpu: [],
})
const loading = ref(false)

// CSS variables are not directly available to el-progress :color; reuse the
// concrete Catppuccin Mocha hex values to keep visuals consistent.
const COLOR_OK   = '#a6e3a1'   // mocha green
const COLOR_WARN = '#fab387'   // mocha peach
const COLOR_ERR  = '#f38ba8'   // mocha red
const getColor = (percent) => {
  if (percent < 50) return COLOR_OK
  if (percent < 80) return COLOR_WARN
  return COLOR_ERR
}

const formatBytes = (bytes) => {
  if (bytes === 0 || !bytes) return '0 B'
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
    ElMessage.error('failed to fetch resources: ' + error.message)
  } finally {
    loading.value = false
  }
}

const registerRefresh   = inject('registerRefresh',   null)
const unregisterRefresh = inject('unregisterRefresh', null)

let timer = null
onMounted(() => {
  refreshResources()
  timer = setInterval(refreshResources, 10000)
  if (registerRefresh) registerRefresh(TAB_NAME, refreshResources)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (unregisterRefresh) unregisterRefresh(TAB_NAME)
})
</script>

<style scoped>
.resources-view {
  padding: 0;
  font-family: var(--font-mono);
  color: var(--fg-text);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
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

.tui-btn-mono {
  font-family: var(--font-mono);
  background: transparent;
  color: var(--fg-subtext);
  border: 1px solid var(--border-strong);
  padding: 4px 14px;
  font-size: 12px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  letter-spacing: 0.4px;
}
.tui-btn-mono:hover { color: var(--accent); border-color: var(--accent); }
.tui-btn-mono.loading { opacity: 0.6; pointer-events: none; }

.resources-view :deep(.el-card__header) {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 10px 14px;
}

.rc-title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-weight: 600;
  color: var(--accent);
}
.rc-meta {
  font-size: 12px;
  color: var(--fg-muted);
  margin-left: auto;
}

.resource-card {
  margin-bottom: 14px;
}

.resource-label {
  font-size: 11.5px;
  color: var(--fg-muted);
  margin: 0 0 6px 0;
  letter-spacing: 0.4px;
  text-transform: lowercase;
}
</style>
