<template>
  <!--
    系统配置视图 / System Configuration View

    中文说明：
    本页面用于展示和修改与服务器 IP 相关的配置。很多下游服务（如 Nginx、
    业务 API 等）在生成访问地址或回调 URL 时，都依赖于统一的 SERVER_IP
    设置，因此需要提供一个简单、安全且可视化的修改入口。

    English description:
    This view exposes a small but important configuration surface: the
    canonical server IP address.  Multiple downstream components rely on
    this value when constructing public URLs or callback endpoints, so the
    UI guides operators through refreshing, validating and persisting the
    correct IP into configuration files.
  -->
  <div class="system-config-view">
    <el-card class="config-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">服务器IP地址配置</span>
        </div>
      </template>
      
      <div class="ip-info-section">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="当前服务器IP">
            <el-tag type="info" size="large">{{ ipInfo.current_ip || '检测中...' }}</el-tag>
            <el-button 
              type="text" 
              size="small" 
              @click="refreshIpInfo"
              :loading="loading"
              style="margin-left: 10px;"
            >
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </el-descriptions-item>
          
          <el-descriptions-item label="配置的IP地址">
            <el-tag 
              :type="ipInfo.needs_update ? 'warning' : 'success'" 
              size="large"
            >
              {{ ipInfo.configured_ip || '未配置' }}
            </el-tag>
          </el-descriptions-item>
          
          <el-descriptions-item label="状态">
            <el-alert
              v-if="ipInfo.needs_update"
              type="warning"
              :closable="false"
              show-icon
            >
              <template #title>
                <strong>IP地址不匹配</strong>
                <p style="margin: 5px 0 0 0; font-size: 12px;">
                  当前服务器IP ({{ ipInfo.current_ip }}) 与配置的IP ({{ ipInfo.configured_ip }}) 不一致
                </p>
              </template>
            </el-alert>
            <el-alert
              v-else-if="ipInfo.configured_ip"
              type="success"
              :closable="false"
              show-icon
            >
              <template #title>
                <strong>IP地址配置正确</strong>
                <p style="margin: 5px 0 0 0; font-size: 12px;">
                  当前服务器IP与配置的IP一致
                </p>
              </template>
            </el-alert>
            <el-alert
              v-else
              type="info"
              :closable="false"
              show-icon
            >
              <template #title>
                <strong>首次配置</strong>
                <p style="margin: 5px 0 0 0; font-size: 12px;">
                  请点击下方按钮将当前IP地址保存到配置中
                </p>
              </template>
            </el-alert>
          </el-descriptions-item>
        </el-descriptions>
      </div>
      
      <div class="action-section" style="margin-top: 30px;">
        <el-button 
          type="primary" 
          size="large"
          @click="updateIp"
          :loading="updating"
          :disabled="!ipInfo.needs_update && ipInfo.configured_ip !== ''"
        >
          <el-icon><Setting /></el-icon>
          {{ ipInfo.configured_ip ? '更新IP配置' : '保存当前IP配置' }}
        </el-button>
        
        <el-button 
          type="info" 
          size="large"
          @click="refreshIpInfo"
          :loading="loading"
          style="margin-left: 10px;"
        >
          <el-icon><Refresh /></el-icon>
          刷新信息
        </el-button>
      </div>
      
      <!-- 更新结果展示 -->
      <el-card v-if="updateResult" class="result-card" style="margin-top: 20px;">
        <template #header>
          <div class="result-header">
            <el-icon :class="updateResult.success ? 'success-icon' : 'error-icon'">
              <component :is="updateResult.success ? 'CircleCheck' : 'CircleClose'" />
            </el-icon>
            <span>{{ updateResult.success ? '更新成功' : '更新失败' }}</span>
          </div>
        </template>
        
        <div class="result-content">
          <p><strong>新IP地址:</strong> {{ updateResult.new_ip }}</p>
          <p v-if="updateResult.message"><strong>消息:</strong> {{ updateResult.message }}</p>
          
          <div v-if="updateResult.restart_results && updateResult.restart_results.length > 0" style="margin-top: 15px;">
            <p><strong>服务重启状态:</strong></p>
            <ul style="margin-left: 20px;">
              <li v-for="(result, index) in updateResult.restart_results" :key="index">
                {{ result.service }}: 
                <el-tag 
                  :type="result.status === 'restarted' ? 'success' : 'danger'" 
                  size="small"
                >
                  {{ result.status }}
                </el-tag>
                <span v-if="result.error" style="color: #f56c6c; margin-left: 10px;">
                  {{ result.error }}
                </span>
              </li>
            </ul>
          </div>
          
          <div v-if="updateResult.script_output" style="margin-top: 15px;">
            <p><strong>脚本输出:</strong></p>
            <pre class="script-output">{{ updateResult.script_output }}</pre>
          </div>
        </div>
      </el-card>
    </el-card>

    <!-- OTA 更新配置 -->
    <el-card class="config-card" shadow="hover" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span class="card-title">远程更新配置</span>
        </div>
      </template>
      <el-form label-width="140px" label-position="left">
        <el-form-item label="更新服务器地址">
          <el-input
            v-model="otaUrl"
            placeholder="https://your-server.com/arbore-updates"
            clearable
            style="max-width: 500px;"
          />
          <div style="font-size: 12px; color: #94a3b8; margin-top: 4px;">
            服务器需托管 version.json、frontend-dist.tar.gz、backend.tar.gz
          </div>
        </el-form-item>
        <el-form-item label="启用自动检测">
          <el-switch v-model="otaEnabled" />
          <span style="margin-left: 8px; color: #94a3b8; font-size: 13px;">启用后每小时自动检查一次新版本</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveOtaConfig" :loading="otaSaving">保存配置</el-button>
          <el-button @click="checkUpdateNow" :loading="otaChecking" :disabled="!otaUrl">立即检查</el-button>
        </el-form-item>
        <el-form-item v-if="otaCheckResult" label="检查结果">
          <el-tag v-if="otaCheckResult.has_update" type="warning">
            有新版本：v{{ otaCheckResult.remote_version }}
          </el-tag>
          <el-tag v-else-if="otaCheckResult.error" type="danger">
            检查失败：{{ otaCheckResult.error }}
          </el-tag>
          <el-tag v-else type="success">
            当前已是最新版本（{{ otaCheckResult.current_version }}）
          </el-tag>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
// 系统配置逻辑（System configuration logic）
// 核心流程：
// 1) refreshIpInfo: 读取当前检测到的服务器 IP 与已保存配置；
// 2) updateIp:      用户确认后，将当前 IP 写入配置并重启相关服务；
// 3) 通过 updateResult 向用户反馈脚本执行结果以及各个服务的重启状态。
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Setting, CircleCheck, CircleClose } from '@element-plus/icons-vue'

const ipInfo = ref({
  current_ip: '',
  configured_ip: '',
  needs_update: false
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
      needs_update: response.data.needs_update || false
    }
  } catch (error) {
    ElMessage.error('获取IP信息失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

const updateIp = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要将配置的IP地址更新为 ${ipInfo.value.current_ip} 吗？\n\n这将：\n1. 更新.env文件中的SERVER_IP\n2. 更新nginx、chat-service等配置文件\n3. 重启相关Docker服务（arbore-flow、arbore-nginx）`,
      '确认更新IP配置',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    updating.value = true
    updateResult.value = null
    
    try {
      const response = await axios.post('/api/v1/system/config/update-ip')
      updateResult.value = response.data
      
      if (response.data.success) {
        ElMessage.success(response.data.message || 'IP配置更新成功')
        // 刷新IP信息
        await refreshIpInfo()
      } else {
        ElMessage.error('IP配置更新失败')
      }
    } catch (error) {
      const errorDetail = error.response?.data?.detail || error.message
      updateResult.value = {
        success: false,
        error: errorDetail
      }
      ElMessage.error('更新IP配置失败: ' + errorDetail)
    }
  } catch (error) {
    // 用户取消
    if (error !== 'cancel') {
      ElMessage.error('操作失败: ' + error.message)
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
    ElMessage.success('更新配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
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

onMounted(() => {
  refreshIpInfo()
  loadOtaConfig()
})
</script>

<style scoped>
.system-config-view {
  padding: 20px 0;
}

.config-card {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 8px;
}

.config-card :deep(.el-card__header) {
  background: rgba(15, 23, 42, 0.5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  color: #f1f5f9;
}

.config-card :deep(.el-card__body) {
  background: rgba(30, 41, 59, 0.3);
  color: #f1f5f9;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-weight: 600;
  font-size: 18px;
  color: #f1f5f9;
}

.ip-info-section {
  margin-bottom: 20px;
}

.ip-info-section :deep(.el-descriptions) {
  background: rgba(15, 23, 42, 0.3);
}

.ip-info-section :deep(.el-descriptions__label) {
  color: #94a3b8;
  font-weight: 500;
}

.ip-info-section :deep(.el-descriptions__content) {
  color: #f1f5f9;
}

.action-section {
  text-align: center;
}

.result-card {
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.1);
}

.result-card :deep(.el-card__header) {
  background: rgba(15, 23, 42, 0.5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  color: #f1f5f9;
}

.result-card :deep(.el-card__body) {
  background: rgba(30, 41, 59, 0.3);
  color: #f1f5f9;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  color: #f1f5f9;
}

.success-icon {
  color: #10b981;
}

.error-icon {
  color: #f56c6c;
}

.result-content {
  color: #94a3b8;
}

.result-content p {
  margin: 8px 0;
}

.result-content strong {
  color: #f1f5f9;
}

.result-content ul {
  color: #94a3b8;
  margin: 10px 0;
}

.result-content li {
  margin: 5px 0;
}

.script-output {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 4px;
  padding: 15px;
  color: #94a3b8;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 300px;
  overflow-y: auto;
}
</style>

