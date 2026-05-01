<template>
  <!--
    自定义服务管理视图 / Custom Services Management View

    中文说明：
    本组件提供“平台内的 PaaS 能力”：用户可以在不修改主系统代码的前提下，
    通过上传 Docker 镜像、配置端口、环境变量和卷挂载等方式，快速在 Arbore
    平台中部署自定义 API 服务。所有自定义服务都通过统一的 Nginx 与 Docker
    编排进行管理。

    English description:
    This view acts as a lightweight PaaS interface inside Arbore.  Operators
    can upload Docker image archives, define ports, environment variables and
    volume mounts, and then manage the lifecycle of custom API services that
    are orchestrated by the backend.  The goal is to make extension services
    first‑class citizens without touching the core product code.
  -->
  <div class="custom-services-view">
    <!-- Page header -->
    <div class="page-header">
      <div class="header-title">
        <h2>custom services</h2>
        <p class="header-desc">
          Upload a Docker image tar and deploy it as a managed service.
        </p>
      </div>
      <el-button type="primary" @click="onAddServiceClick">
        <Plus style="margin-right: 4px;" />
        add service
      </el-button>
    </div>

    <!-- Service list -->
    <el-card class="services-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">service list</span>
          <el-button link @click="refreshServices" :loading="loading">
            <Refresh style="margin-right: 4px;" />
            refresh
          </el-button>
        </div>
      </template>

      <el-table
        :data="services"
        v-loading="loading"
        stripe
        style="width: 100%"
        :empty-text="loading ? 'loading...' : 'no custom services'"
      >
        <el-table-column label="icon" width="80" align="center">
          <template #default="{ row }">
            <div class="service-icon-cell">
              <component
                :is="getIconComponent(row.icon || 'Box')"
                class="service-icon"
                :style="{ fontSize: '22px' }"
              />
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="name" width="180">
          <template #default="{ row }">
            <span class="cs-mono">{{ row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="description" label="description" min-width="200">
          <template #default="{ row }">
            <span class="description-text">{{ row.description || 'no description' }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="port" label="port" width="100" align="center">
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ row.port }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="status" width="150" align="center">
          <template #default="{ row }">
            <div class="status-cell">
              <el-tag
                :type="getStatusType(row.status)"
                size="small"
                style="margin-bottom: 4px;"
              >
                {{ getStatusText(row.status) }}
              </el-tag>
              <div v-if="row.health && row.health !== 'unknown' && row.health !== 'none'" style="margin-top: 4px;">
                <el-tag
                  :type="row.health === 'healthy' ? 'success' : (row.health === 'unhealthy' ? 'danger' : 'warning')"
                  size="small"
                >
                  {{ getHealthText(row.health, row.status) }}
                </el-tag>
              </div>
              <div v-if="row.container_id" class="cs-id">
                id: {{ row.container_id }}
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="url" width="250">
          <template #default="{ row }">
            <el-link
              :href="getServiceUrl(row)"
              target="_blank"
              type="primary"
              underline="never"
            >
              {{ getServiceUrl(row) }}
            </el-link>
          </template>
        </el-table-column>

        <el-table-column label="actions" width="320" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="info"    size="small" @click="showServiceDetails(row)">details</el-button>
            <el-button v-if="row.has_doc"
                       link type="success" size="small" @click="viewServiceDoc(row)">doc</el-button>
            <el-button link type="primary" size="small" @click="editService(row)">edit</el-button>
            <el-button link type="warning" size="small" @click="restartService(row)">restart</el-button>
            <el-button link type="danger"  size="small" @click="deleteService(row)">delete</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Service details dialog -->
    <el-dialog
      v-model="showDetailsDialog"
      title="service details"
      width="80%"
      :close-on-click-modal="false"
      @close="handleDetailsDialogClose"
    >
      <div v-if="selectedService" class="service-details">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="name">{{ selectedService.name }}</el-descriptions-item>
          <el-descriptions-item label="port">{{ selectedService.port }}</el-descriptions-item>
          <el-descriptions-item label="description">{{ selectedService.description }}</el-descriptions-item>
          <el-descriptions-item label="status">
            <el-tag :type="getStatusType(selectedService.status)" size="small">
              {{ getStatusText(selectedService.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="health" v-if="selectedService.health && selectedService.health !== 'unknown'">
            <el-tag
              :type="selectedService.health === 'healthy' ? 'success' : (selectedService.health === 'unhealthy' ? 'danger' : 'warning')"
              size="small"
            >
              {{ getHealthText(selectedService.health, selectedService.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="container id" v-if="selectedService.container_id">
            {{ selectedService.container_id }}
          </el-descriptions-item>
          <el-descriptions-item label="url" :span="2">
            <el-link :href="getServiceUrl(selectedService)" target="_blank" type="primary">
              {{ getServiceUrl(selectedService) }}
            </el-link>
          </el-descriptions-item>
          <el-descriptions-item label="documentation" :span="2">
            <template v-if="selectedService.has_doc">
              <el-button type="primary" size="small" @click="viewServiceDoc(selectedService)">
                view pdf
              </el-button>
            </template>
            <span v-else class="text-muted">not uploaded</span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="logs-section" style="margin-top: 20px;">
          <div class="logs-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h3>container logs</h3>
            <div>
              <el-select v-model="logTail" size="small" style="width: 130px; margin-right: 10px;" @change="loadServiceLogs">
                <el-option label="last 100"  :value="100" />
                <el-option label="last 500"  :value="500" />
                <el-option label="last 1000" :value="1000" />
              </el-select>
              <el-button size="small" @click="loadServiceLogs" :loading="logsLoading">
                <Refresh style="margin-right: 4px;" />
                refresh
              </el-button>
            </div>
          </div>
          <el-scrollbar height="400px" class="logs-container">
            <pre class="logs-content">{{ serviceLogs }}</pre>
          </el-scrollbar>
        </div>
      </div>
    </el-dialog>

    <!-- Add / edit service dialog -->
    <el-dialog
      v-model="showAddDialog"
      :title="editingService ? 'edit service' : 'add service'"
      width="600px"
      :close-on-click-modal="false"
      @close="handleDialogClose"
    >
      <el-form
        ref="serviceFormRef"
        :model="serviceForm"
        :rules="formRules"
        label-width="140px"
        label-position="left"
      >
        <el-form-item label="icon" prop="icon">
          <div class="icon-selector-wrapper">
            <el-button class="icon-selector-trigger" @click="showIconSelector = true">
              <component :is="getIconComponent(serviceForm.icon)" class="icon-trigger-icon" />
              <span class="icon-trigger-text">choose icon</span>
            </el-button>
            <div class="icon-preview-container">
              <component :is="getIconComponent(serviceForm.icon)" class="icon-preview-large" />
              <span class="icon-preview-name">{{ getIconLabel(serviceForm.icon) }}</span>
            </div>
          </div>

          <!-- Icon picker dialog -->
          <el-dialog
            v-model="showIconSelector"
            title="choose icon"
            width="800px"
            :close-on-click-modal="true"
            class="icon-selector-dialog"
          >
            <div class="icon-selector-search">
              <el-input
                v-model="iconSearchText"
                placeholder="search icons..."
                clearable
                :prefix-icon="Search"
              />
            </div>

            <div class="icon-selector-grid">
              <div
                v-for="icon in filteredIcons"
                :key="icon.name"
                class="icon-grid-item"
                :class="{ active: serviceForm.icon === icon.name }"
                @click="selectIcon(icon.name)"
                :title="icon.label"
              >
                <component :is="icon.component" class="icon-grid-icon" />
              </div>
            </div>
          </el-dialog>
        </el-form-item>

        <el-form-item label="name" prop="name">
          <el-input
            v-model="serviceForm.name"
            placeholder="e.g. my-api-service"
            :disabled="!!editingService"
            @blur="handleNameBlur"
          />
          <div class="form-tip">lowercase letters, digits and hyphens only</div>
        </el-form-item>

        <el-form-item label="description" prop="description">
          <el-input
            v-model="serviceForm.description"
            type="textarea"
            :rows="2"
            placeholder="enter service description"
          />
        </el-form-item>

        <el-form-item label="host port" prop="port">
          <el-input-number
            v-model="serviceForm.port"
            :min="7000"
            :max="7999"
            :step="1"
            style="width: 100%"
          />
          <div class="form-tip">port range 7000-7999. external url: http://server-ip:port</div>
        </el-form-item>

        <el-form-item label="container port" prop="container_port">
          <el-input-number
            v-model="serviceForm.container_port"
            :min="1"
            :max="65535"
            :step="1"
            style="width: 100%"
          />
          <div class="form-tip">
            internal port the container listens on. defaults to host port. if the
            service hardcodes a different port (e.g. 8000), set it here and the
            system will map it to the host port automatically.
          </div>
        </el-form-item>

        <el-form-item label="memory limit (mb)" prop="memory_limit_mb">
          <el-input-number
            v-model="serviceForm.memory_limit_mb"
            :min="0"
            :max="65536"
            :step="256"
            style="width: 100%"
            placeholder="leave empty for no limit"
            controls-position="right"
          />
          <div class="form-tip">max memory the container may use (mb). e.g. 4096 = 4 gb. restart required to apply.</div>
        </el-form-item>
        <el-form-item label="memory reservation (mb)" prop="memory_reservation_mb">
          <el-input-number
            v-model="serviceForm.memory_reservation_mb"
            :min="0"
            :max="65536"
            :step="256"
            style="width: 100%"
            placeholder="optional"
            controls-position="right"
          />
          <div class="form-tip">soft memory reservation (mb). optional. restart required to apply.</div>
        </el-form-item>

        <el-form-item
          v-if="!editingService"
          label="docker image"
          prop="file"
        >
          <div class="file-upload-wrapper">
            <input
              id="file-input-tar"
              type="file"
              accept=".tar"
              style="display: none;"
              @change="handleFileInputChange"
            />
            <label for="file-input-tar" class="file-input-label">
              <el-button type="primary" style="pointer-events: none;">
                <Upload style="margin-right: 4px;" />
                choose tar file
              </el-button>
            </label>
            <div v-if="serviceForm.file" class="file-name">
              {{ serviceForm.file.name }}
            </div>
            <div class="form-tip">
              upload a packaged docker image .tar file
            </div>
          </div>
        </el-form-item>

        <!-- Documentation upload -->
        <el-form-item label="documentation">
          <div class="file-upload-wrapper">
            <input
              id="file-input-doc"
              type="file"
              accept=".pdf"
              style="display: none;"
              @change="handleDocFileChange"
            />
            <label for="file-input-doc" class="file-input-label">
              <el-button type="success" style="pointer-events: none;">
                <Upload style="margin-right: 4px;" />
                choose pdf
              </el-button>
            </label>
            <div v-if="serviceForm.docFile" class="file-name">
              {{ serviceForm.docFile.name }}
              <el-button link type="danger" size="small" @click="removeDocFile" style="margin-left: 8px;">remove</el-button>
            </div>
            <div v-else-if="editingService && editingService.has_doc" class="file-name">
              <el-tag type="success" size="small">doc available</el-tag>
              <el-button link type="primary" size="small" @click="viewServiceDoc(editingService)"  style="margin-left: 8px;">view</el-button>
              <el-button link type="danger"  size="small" @click="deleteServiceDoc(editingService)" style="margin-left: 4px;">delete doc</el-button>
            </div>
            <div class="form-tip">
              optional pdf documentation that will be available later in details.
            </div>
          </div>
        </el-form-item>

        <!-- Env vars -->
        <el-form-item label="env vars">
          <el-tabs v-model="envTabType" class="env-vars-tabs">
            <el-tab-pane label="form" name="form">
              <div class="env-vars-form">
                <div
                  v-for="(item, index) in envVars"
                  :key="index"
                  class="env-var-item"
                >
                  <el-input
                    v-model="item.key"
                    placeholder="key"
                    style="width: 200px; margin-right: 8px;"
                  />
                  <el-input
                    v-model="item.value"
                    placeholder="value"
                    type="password"
                    show-password
                    style="flex: 1; margin-right: 8px;"
                  />
                  <el-button type="danger" link @click="removeEnvVar(index)">remove</el-button>
                </div>
                <el-button type="primary" link @click="addEnvVar" style="margin-top: 8px;">
                  + add variable
                </el-button>
              </div>
            </el-tab-pane>
            <el-tab-pane label="json" name="json">
              <el-input
                v-model="envVarsJson"
                type="textarea"
                :rows="8"
                placeholder='{"AUTH_ENABLED": "true", "SM4_KEY": "your_key"}'
                class="env-vars-json-input"
              />
              <div class="form-tip">
                json object, e.g. {"KEY1": "value1", "KEY2": "value2"}
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-form-item>

        <!-- Volumes -->
        <el-form-item label="volumes">
          <el-tabs v-model="volumesTabType" class="env-vars-tabs">
            <el-tab-pane label="form" name="form">
              <div class="env-vars-form">
                <div
                  v-for="(item, index) in volumesList"
                  :key="index"
                  class="env-var-item"
                >
                  <el-input
                    v-model="item.hostPath"
                    placeholder="host path (e.g. /path/to/huggingface/models)"
                    style="flex: 1; margin-right: 8px;"
                  />
                  <el-input
                    v-model="item.containerPath"
                    placeholder="container path (e.g. /models)"
                    style="flex: 1; margin-right: 8px;"
                  />
                  <el-checkbox v-model="item.readOnly" style="margin-right: 8px;">read-only</el-checkbox>
                  <el-button type="danger" link @click="removeVolume(index)">remove</el-button>
                </div>
                <el-button type="primary" link @click="addVolume" style="margin-top: 8px;">
                  + add mount
                </el-button>
              </div>
            </el-tab-pane>
            <el-tab-pane label="json" name="json">
              <el-input
                v-model="volumesJson"
                type="textarea"
                :rows="6"
                placeholder='["/path/to/huggingface/models:/models", "/path/to/data:/data:ro"]'
                class="env-vars-json-input"
              />
              <div class="form-tip">
                json array of strings, format: "host_path:container_path" or
                "host_path:container_path:ro" (ro = read-only).
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-form-item>

        <el-form-item v-if="!editingService">
          <el-alert type="info" :closable="false" show-icon>
            <template #default>
              <span class="alert-text">
                custom service ports range 7000-7999. nginx routes by path; the
                whole range is exposed through a single nginx entry point.
              </span>
            </template>
          </el-alert>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="showAddDialog = false">cancel</el-button>
          <el-button
            type="primary"
            @click="submitService"
            :loading="submitting"
          >
            {{ editingService ? 'update' : 'deploy' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!--
      Upload progress dialog
      ------------------------------------------------------------------
      Shown only while a tar is being uploaded for a new custom service.
      Two progress bars are stacked so the user always sees motion:
        1) browser -> webadmin-api (XHR upload progress event in bytes)
        2) webadmin-api -> Portainer + container lifecycle (NDJSON events
           streamed back from the backend via the same XHR channel)
    -->
    <el-dialog
      v-model="uploadProgress.visible"
      :title="uploadProgress.title"
      width="540px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="uploadProgress.finished"
      class="upload-progress-dialog"
      append-to-body
    >
      <div class="upload-progress-body">
        <div class="up-section">
          <div class="up-section-head">
            <span class="up-section-title">browser → server (image upload)</span>
            <span class="up-section-pct">{{ uploadProgress.uploadPct }}%</span>
          </div>
          <el-progress
            :percentage="uploadProgress.uploadPct"
            :status="uploadProgress.uploadStatus"
            :stroke-width="14"
          />
          <div class="up-section-meta">
            {{ formatBytes(uploadProgress.uploadedBytes) }}
            <span v-if="uploadProgress.totalBytes"> / {{ formatBytes(uploadProgress.totalBytes) }}</span>
            <span v-if="uploadProgress.uploadSpeed" class="up-speed">
              · {{ formatBytes(uploadProgress.uploadSpeed) }}/s
            </span>
          </div>
        </div>

        <div class="up-section">
          <div class="up-section-head">
            <span class="up-section-title">server processing</span>
            <span class="up-section-pct">{{ uploadProgress.serverPct }}%</span>
          </div>
          <el-progress
            :percentage="uploadProgress.serverPct"
            :status="uploadProgress.serverStatus"
            :stroke-width="14"
            :indeterminate="uploadProgress.serverIndeterminate"
            :duration="3"
          />
          <div class="up-stages">
            <div
              v-for="stage in uploadProgress.stages"
              :key="stage.key"
              class="up-stage-row"
              :class="['stage-' + stage.state]"
            >
              <el-icon class="up-stage-icon">
                <component :is="stageIconFor(stage.state)" />
              </el-icon>
              <span class="up-stage-label">{{ stage.label }}</span>
              <span v-if="stage.message" class="up-stage-msg">{{ stage.message }}</span>
            </div>
          </div>
        </div>

        <el-alert
          v-if="uploadProgress.errorMessage"
          type="error"
          :closable="false"
          show-icon
          :title="'deployment failed' + (uploadProgress.errorStage ? ' (stage: ' + stageLabelOf(uploadProgress.errorStage) + ')' : '')"
          :description="uploadProgress.errorMessage"
          style="margin-top: 14px;"
        />

        <el-alert
          v-if="uploadProgress.success"
          type="success"
          :closable="false"
          show-icon
          title="deployment succeeded"
          description="service deployed and running. it is visible in the list above."
          style="margin-top: 14px;"
        />
      </div>

      <template #footer>
        <el-button
          v-if="!uploadProgress.finished"
          type="danger"
          plain
          @click="cancelUpload"
        >cancel upload</el-button>
        <el-button
          v-if="uploadProgress.finished"
          type="primary"
          @click="closeUploadDialog"
        >close</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
// 自定义服务管理逻辑（Custom services management logic）
// 主要职责：
// 1) 通过 /admin-api/api/v1/custom-services 系列接口，完成服务的增删改查；
// 2) 在表单中收集镜像、端口、环境变量、卷挂载等与容器编排直接相关的信息；
// 3) 集成许可证校验逻辑，确保仅在已注册授权的环境中开启自定义服务功能。
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch, inject } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const setActiveTab     = inject('setActiveTab',     null)
const registerRefresh  = inject('registerRefresh',  null)
const unregisterRefresh = inject('unregisterRefresh', null)
const registerSearch   = inject('registerSearch',   null)
const unregisterSearch = inject('unregisterSearch', null)
const TAB_NAME = 'custom-services'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import {
  Search, Plus, Refresh, Upload,
  Loading, Check, CircleCheck, Clock, CircleClose,
} from '@element-plus/icons-vue'

const services = ref([])
const loading = ref(false)
const submitting = ref(false)
const showAddDialog = ref(false)
const showIconSelector = ref(false)
const iconSearchText = ref('')
const editingService = ref(null)
const serviceFormRef = ref(null)
// 不再需要 fileInputRef，使用原生 label + input 方式

// 环境变量配置
const envTabType = ref('form')
const envVars = ref([])
const envVarsJson = ref('')

// 卷挂载配置
const volumesTabType = ref('form')
const volumesList = ref([])
const volumesJson = ref('')

// 服务详情
const showDetailsDialog = ref(false)
const selectedService = ref(null)
const serviceLogs = ref('')
const logsLoading = ref(false)
const logTail = ref(100)

const serviceForm = reactive({
  name: '',
  description: '',
  port: 7000,  // 宿主机端口，默认7000，可在7000-7999范围内选择
  container_port: 7000,  // 容器内端口，默认等于宿主机端口
  memory_limit_mb: null,  // 内存限制（MB），可选
  memory_reservation_mb: null,  // 内存预留（MB），可选
  icon: 'Box',  // 默认图标
  file: null,
  docFile: null
})

// 记录上一次的port值，用于判断是否需要自动同步container_port
let previousPort = 7000

// 监听port变化，如果container_port等于旧的port值，则自动同步
watch(() => serviceForm.port, (newPort, oldPort) => {
  // 如果container_port等于旧的port值，说明用户还没有手动修改过，自动同步
  if (serviceForm.container_port === oldPort || serviceForm.container_port === previousPort) {
    serviceForm.container_port = newPort
  }
  previousPort = newPort
})

// 添加环境变量
const addEnvVar = () => {
  envVars.value.push({ key: '', value: '' })
}

// 删除环境变量
const removeEnvVar = (index) => {
  envVars.value.splice(index, 1)
}

// 添加卷挂载
const addVolume = () => {
  volumesList.value.push({ hostPath: '', containerPath: '', readOnly: false })
}

// 删除卷挂载
const removeVolume = (index) => {
  volumesList.value.splice(index, 1)
}

// 将环境变量转换为JSON
const getEnvVarsJson = () => {
  if (envTabType.value === 'json') {
    // JSON模式：直接返回JSON字符串
    if (!envVarsJson.value.trim()) {
      return null
    }
    try {
      // 验证JSON格式
      JSON.parse(envVarsJson.value)
      return envVarsJson.value
    } catch (e) {
      throw new Error('env vars json is invalid')
    }
  } else {
    // 表单模式：转换为JSON
    const envObj = {}
    envVars.value.forEach(item => {
      if (item.key && item.value) {
        envObj[item.key] = item.value
      }
    })
    if (Object.keys(envObj).length === 0) {
      return null
    }
    return JSON.stringify(envObj)
  }
}

// 将卷挂载转换为JSON
const getVolumesJson = () => {
  if (volumesTabType.value === 'json') {
    // JSON模式：直接返回JSON字符串
    if (!volumesJson.value.trim()) {
      return null
    }
    try {
      // 验证JSON格式
      const parsed = JSON.parse(volumesJson.value)
      if (!Array.isArray(parsed)) {
        throw new Error('volumes must be a json array')
      }
      return volumesJson.value
    } catch (e) {
      throw new Error('volumes json is invalid: ' + e.message)
    }
  } else {
    // 表单模式：转换为JSON数组
    const volumesArray = []
    volumesList.value.forEach(item => {
      if (item.hostPath && item.containerPath) {
        let volumeStr = `${item.hostPath}:${item.containerPath}`
        if (item.readOnly) {
          volumeStr += ':ro'
        }
        volumesArray.push(volumeStr)
      }
    })
    if (volumesArray.length === 0) {
      return null
    }
    return JSON.stringify(volumesArray)
  }
}

// 获取所有可用的图标（从ElementPlusIconsVue中提取）
const getAllAvailableIcons = () => {
  const iconNames = Object.keys(ElementPlusIconsVue)
  // 过滤掉一些不常用的图标，保留常用和有用的
  const excludeIcons = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Close', 'Check', 'Loading']
  return iconNames
    .filter(name => !excludeIcons.includes(name))
    .map(name => ({
      name,
      component: ElementPlusIconsVue[name],
      label: name.replace(/([A-Z])/g, ' $1').trim()
    }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

const availableIcons = getAllAvailableIcons()

// 计算过滤后的图标列表
const filteredIcons = computed(() => {
  if (!iconSearchText.value) {
    return availableIcons
  }
  const query = iconSearchText.value.toLowerCase()
  return availableIcons.filter(icon => 
    icon.label.toLowerCase().includes(query) ||
    icon.name.toLowerCase().includes(query)
  )
})

// 获取图标组件
const getIconComponent = (iconName) => {
  return ElementPlusIconsVue[iconName] || ElementPlusIconsVue.Box
}

// 获取图标标签
const getIconLabel = (iconName) => {
  const icon = availableIcons.find(i => i.name === iconName)
  return icon ? icon.label : 'Box'
}

// 选择图标
const selectIcon = (iconName) => {
  serviceForm.icon = iconName
  showIconSelector.value = false
  iconSearchText.value = ''
}

// 服务名称失焦时，如果端点为空，自动填充
// 服务名称失焦时的处理（不再需要自动填充endpoint）
const handleNameBlur = () => {
  // endpoint已移除，现在通过端口直接访问
}

const formRules = {
  name: [
    { required: true, message: 'name is required', trigger: 'blur' },
    {
      pattern: /^[a-z0-9-]+$/,
      message: 'name may only contain lowercase letters, digits and hyphens',
      trigger: 'blur',
    },
  ],
  description: [
    { required: true, message: 'description is required', trigger: 'blur' },
  ],
  port: [
    { required: true, message: 'port is required', trigger: 'blur' },
    {
      type: 'number',
      min: 7000,
      max: 7999,
      message: 'port must be in the 7000-7999 range',
      trigger: 'blur',
    },
  ],
  file: [
    {
      validator: (rule, value, callback) => {
        if (!editingService.value && !serviceForm.file) {
          callback(new Error('select a docker image tar file'))
        } else {
          callback()
        }
      },
      trigger: 'change',
    },
  ],
}

const getServerIP = () => {
  return window.location.hostname
}

const getServiceUrl = (service) => {
  // 直接使用端口访问，与页面协议一致（HTTP/HTTPS 自动切换）
  return `${window.location.protocol}//${getServerIP()}:${service.port}`
}

// 获取状态类型（用于el-tag的type属性）
const getStatusType = (status) => {
  if (!status) return 'info'
  const statusLower = status.toLowerCase()
  if (statusLower === 'running') return 'success'
  if (statusLower === 'stopped' || statusLower === 'exited') return 'danger'
  if (statusLower === 'restarting') return 'warning'
  if (statusLower === 'not_found') return 'info'
  return 'info'
}

// 获取状态文本（英文显示）
const getStatusText = (status) => {
  if (!status) return 'unknown'
  const statusLower = status.toLowerCase()
  const statusMap = {
    'running':    'running',
    'stopped':    'stopped',
    'exited':     'exited',
    'restarting': 'restarting',
    'paused':     'paused',
    'not_found':  'not found',
    'created':    'created',
    'removing':   'removing',
  }
  return statusMap[statusLower] || statusLower
}

// 获取健康状态文本（英文显示）
const getHealthText = (health, containerStatus) => {
  if (!health) return 'unknown'
  const healthLower = health.toLowerCase()
  const statusLower = containerStatus ? containerStatus.toLowerCase() : ''

  // 容器已 running 但 health 还在 starting，明确告诉用户在做健康检查
  if (healthLower === 'starting' && statusLower === 'running') {
    return 'health-checking'
  }

  const healthMap = {
    'healthy':   'healthy',
    'unhealthy': 'unhealthy',
    'starting':  'starting',
    'none':      'no check',
  }
  return healthMap[healthLower] || healthLower
}

const refreshServices = async () => {
  loading.value = true
  try {
    console.log('Fetching custom services from /admin-api/api/v1/custom-services')
    const response = await axios.get('/admin-api/api/v1/custom-services')
    console.log('API response:', response.data)
    services.value = response.data.services || []
    console.log('Services loaded:', services.value.length, 'services')
    if (services.value.length === 0) {
      console.warn('No services returned from API')
    }
  } catch (error) {
    console.error('Failed to fetch services:', error)
    console.error('Error response:', error.response)
    ElMessage.error('failed to fetch services: ' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

// 不再需要 triggerFileSelect 函数，使用原生 label + input 方式

const handleFileInputChange = (event) => {
  const file = event.target.files?.[0]
  if (file) {
    serviceForm.file = file
    console.log('File selected:', file.name)
  }
}

const handleDocFileChange = (event) => {
  const file = event.target.files?.[0]
  if (file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      ElMessage.error('only pdf documentation is supported')
      return
    }
    serviceForm.docFile = file
    console.log('Doc file selected:', file.name)
  }
}

const removeDocFile = () => {
  serviceForm.docFile = null
  const docInput = document.getElementById('file-input-doc')
  if (docInput) docInput.value = ''
}

const viewServiceDoc = (service) => {
  window.open(`/admin-api/api/v1/custom-services/${service.name}/doc`, '_blank')
}

const deleteServiceDoc = async (service) => {
  try {
    await ElMessageBox.confirm('delete the documentation file for this service?', 'confirm delete', {
      confirmButtonText: 'delete',
      cancelButtonText: 'cancel',
      type: 'warning',
    })
    await axios.delete(`/admin-api/api/v1/custom-services/${service.name}/doc`)
    ElMessage.success('documentation deleted')
    service.has_doc = false
    if (editingService.value) {
      editingService.value.has_doc = false
    }
    await refreshServices()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('failed to delete documentation: ' + (error.response?.data?.detail || error.message))
    }
  }
}

// 点击「添加服务」时先校验许可证，未注册则跳转到许可证页
async function onAddServiceClick() {
  try {
    const res = await axios.get('/admin-api/api/v1/license')
    if (res.data.valid === true && res.data.registered === true) {
      editingService.value = null
      resetForm()
      showAddDialog.value = true
      return
    }
    ElMessage.warning('register a license before adding custom services')
    if (typeof setActiveTab === 'function') {
      setActiveTab('license')
    }
  } catch (err) {
    ElMessage.error('failed to verify registration: ' + (err.response?.data?.detail?.message || err.message))
    if (typeof setActiveTab === 'function') {
      setActiveTab('license')
    }
  }
}


const submitService = async () => {
  if (!serviceFormRef.value) return

  // endpoint验证已移除，现在通过端口直接访问

  await serviceFormRef.value.validate(async (valid) => {
    if (!valid) return

    submitting.value = true
    try {
      if (editingService.value) {
        // 更新服务
        const updateData = {
          port: serviceForm.port,
          description: serviceForm.description,
          icon: serviceForm.icon
        }
        // 如果容器端口与宿主机端口不同，才添加到更新数据
        if (serviceForm.container_port && serviceForm.container_port !== serviceForm.port) {
          updateData.container_port = serviceForm.container_port
        }
        // 内存限制（含 null 表示取消限制），修改后需重启生效
        if (serviceForm.memory_limit_mb !== undefined) {
          updateData.memory_limit_mb = serviceForm.memory_limit_mb
        }
        if (serviceForm.memory_reservation_mb !== undefined) {
          updateData.memory_reservation_mb = serviceForm.memory_reservation_mb
        }
        
        // 添加环境变量配置（如果配置了）
        try {
          const envVarsJsonStr = getEnvVarsJson()
          if (envVarsJsonStr) {
            updateData.env_vars = envVarsJsonStr
          }
        } catch (error) {
          ElMessage.error(error.message || 'invalid env vars')
          submitting.value = false
          return
        }

        // 添加卷挂载配置（如果配置了）
        try {
          const volumesJsonStr = getVolumesJson()
          if (volumesJsonStr) {
            updateData.volumes = volumesJsonStr
          }
        } catch (error) {
          ElMessage.error(error.message || 'invalid volumes')
          submitting.value = false
          return
        }
        
        await axios.put(
          `/admin-api/api/v1/custom-services/${editingService.value.name}`,
          updateData
        )
        
        // 如果选择了新的说明文档，单独上传
        if (serviceForm.docFile) {
          try {
            const docFormData = new FormData()
            docFormData.append('doc_file', serviceForm.docFile)
            await axios.post(
              `/admin-api/api/v1/custom-services/${editingService.value.name}/doc`,
              docFormData,
              { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 }
            )
          } catch (docErr) {
            console.error('failed to upload documentation:', docErr)
            ElMessage.warning('service updated but documentation upload failed')
          }
        }

        ElMessage.success('service updated')
      } else {
        // 添加服务
        if (!serviceForm.file) {
          ElMessage.error('select a docker image tar file')
          submitting.value = false
          return
        }

        // 第一步：先验证参数（不涉及文件上传，快速返回）
        try {
          const validateFormData = new FormData()
          validateFormData.append('name', serviceForm.name)
          validateFormData.append('port', serviceForm.port)
          // 如果容器端口与宿主机端口不同，才添加到验证数据
          if (serviceForm.container_port && serviceForm.container_port !== serviceForm.port) {
            validateFormData.append('container_port', serviceForm.container_port)
          }
          // endpoint参数已移除，现在通过端口直接访问
          
          await axios.post('/admin-api/api/v1/custom-services/validate', validateFormData, {
            headers: {
              'Content-Type': 'multipart/form-data'
            },
            timeout: 10000 // 10秒超时（验证应该很快）
          })
        } catch (error) {
          // 验证失败，立即返回，不进行文件上传
          let errorMessage = 'validation failed'
          if (error.response?.data?.detail) {
            errorMessage = error.response.data.detail
          } else if (error.response) {
            errorMessage = `server error: ${error.response.status} ${error.response.statusText}`
          }
          ElMessage.error('deploy failed: ' + errorMessage)
          submitting.value = false
          return
        }

        // 第二步：验证通过后，再上传文件
        const formData = new FormData()
        formData.append('file', serviceForm.file)
        formData.append('name', serviceForm.name)
        formData.append('port', serviceForm.port)
        // 如果容器端口与宿主机端口不同，才添加到表单数据
        if (serviceForm.container_port && serviceForm.container_port !== serviceForm.port) {
          formData.append('container_port', serviceForm.container_port)
        }
        // endpoint参数已移除，现在通过端口直接访问
        formData.append('description', serviceForm.description)
        formData.append('icon', serviceForm.icon)
        if (serviceForm.memory_limit_mb != null && serviceForm.memory_limit_mb !== '') {
          formData.append('memory_limit_mb', serviceForm.memory_limit_mb)
        }
        if (serviceForm.memory_reservation_mb != null && serviceForm.memory_reservation_mb !== '') {
          formData.append('memory_reservation_mb', serviceForm.memory_reservation_mb)
        }
        
        // 添加环境变量配置
        try {
          const envVarsJsonStr = getEnvVarsJson()
          console.log('env vars payload:', envVarsJsonStr)
          if (envVarsJsonStr && envVarsJsonStr.trim()) {
            formData.append('env_vars', envVarsJsonStr)
          }
        } catch (error) {
          ElMessage.error(error.message || 'invalid env vars')
          submitting.value = false
          return
        }

        // 添加卷挂载配置
        try {
          const volumesJsonStr = getVolumesJson()
          console.log('volumes payload:', volumesJsonStr)
          if (volumesJsonStr && volumesJsonStr.trim()) {
            formData.append('volumes', volumesJsonStr)
          }
        } catch (error) {
          ElMessage.error(error.message || 'invalid volumes')
          submitting.value = false
          return
        }

        // 添加说明文档
        if (serviceForm.docFile) {
          formData.append('doc_file', serviceForm.docFile)
        }

        // 走流式上传：XHR 发请求，前端解析 NDJSON 事件实时显示进度
        await uploadWithProgress(formData)

        ElMessage.success('service deployed')
      }

      showAddDialog.value = false
      resetForm()
      await refreshServices()
    } catch (error) {
      console.error('service operation failed:', error)
      let errorMessage = 'unknown error'

      if (error && error.isUploadFailure) {
        // 流式上传里抛出的错误，已经在弹窗里展示，这里只静默 toast 简短提示
        errorMessage = error.message || 'upload failed'
        ElMessage.error('deploy failed: ' + errorMessage)
        submitting.value = false
        return
      }

      if (error.response) {
        const detail = error.response.data?.detail || error.response.data?.message
        if (detail) {
          errorMessage = detail
        } else {
          errorMessage = `server error: ${error.response.status} ${error.response.statusText}`
        }
      } else if (error.request) {
        errorMessage = 'cannot reach server — is the backend running?'
      } else {
        errorMessage = error.message || 'unknown error'
      }

      ElMessage.error(
        (editingService.value ? 'update' : 'deploy') +
        ' failed: ' + errorMessage,
      )
    } finally {
      submitting.value = false
    }
  })
}

// ----------------------------------------------------------------------------
// 流式上传 + 进度展示
// ----------------------------------------------------------------------------
// 后端返回 NDJSON：每行一个事件 {phase, message, ...}
// 前端用 XHR 同步监听上传字节进度（xhr.upload.onprogress），并在 readyState=3
// 时增量解析 responseText 中的 NDJSON 行，把阶段更新到 uploadProgress。
const STAGE_DEFS = [
  { key: 'validating',             label: 'validate config' },
  { key: 'uploading_to_portainer', label: 'transfer to portainer and load image' },
  { key: 'image_loaded',           label: 'image loaded', virtual: true },
  { key: 'creating_container',     label: 'create container' },
  { key: 'starting_container',     label: 'start container' },
  { key: 'saving_doc',             label: 'save documentation' },
]

const uploadProgress = reactive({
  visible: false,
  title: 'deploy service',
  finished: false,
  success: false,
  // 浏览器 -> 服务器 上传进度
  uploadPct: 0,
  uploadStatus: '',
  uploadedBytes: 0,
  totalBytes: 0,
  uploadSpeed: 0,
  // 服务器处理进度
  serverPct: 0,
  serverStatus: '',
  serverIndeterminate: false,
  stages: [],
  // 错误
  errorMessage: '',
  errorStage: '',
})

let currentXhr = null
let lastProgressTime = 0
let lastProgressBytes = 0

const initStages = () => {
  uploadProgress.stages = STAGE_DEFS
    .filter(s => !s.virtual)
    .map(s => ({ key: s.key, label: s.label, state: 'pending', message: '' }))
}

const stageLabelOf = (key) => {
  const s = STAGE_DEFS.find(x => x.key === key)
  return s ? s.label : key
}

const stageIconFor = (state) => {
  if (state === 'done') return CircleCheck
  if (state === 'active') return Loading
  if (state === 'error') return CircleClose
  return Clock
}

const formatBytes = (b) => {
  if (!b) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = b
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2) + ' ' + units[i]
}

const setStageState = (key, state, message = '') => {
  const s = uploadProgress.stages.find(x => x.key === key)
  if (s) {
    s.state = state
    if (message) s.message = message
  }
}

const advanceServerStageTo = (key, message = '') => {
  // 把 key 之前的全部置为 done，key 自己置为 active，之后保持 pending
  let hit = false
  for (const s of uploadProgress.stages) {
    if (s.key === key) {
      s.state = 'active'
      s.message = message
      hit = true
    } else if (!hit) {
      if (s.state !== 'done') s.state = 'done'
    }
  }
  // 计算服务器处理进度百分比（按已完成阶段数 / 总阶段数）
  const total = uploadProgress.stages.length
  const done = uploadProgress.stages.filter(s => s.state === 'done').length
  uploadProgress.serverPct = Math.min(99, Math.round(((done + 0.4) / total) * 100))
  uploadProgress.serverIndeterminate = false
}

const handleEvent = (ev) => {
  switch (ev.phase) {
    case 'validating':
      advanceServerStageTo('validating', ev.message || '')
      break
    case 'uploading_to_portainer':
      advanceServerStageTo('uploading_to_portainer', ev.message || '')
      break
    case 'image_loaded': {
      // image_loaded 表示 uploading_to_portainer 已完成
      const s = uploadProgress.stages.find(x => x.key === 'uploading_to_portainer')
      if (s) { s.state = 'done'; s.message = ev.message || s.message }
      break
    }
    case 'creating_container':
      advanceServerStageTo('creating_container', ev.message || '')
      break
    case 'starting_container':
      advanceServerStageTo('starting_container', ev.message || '')
      break
    case 'saving_doc':
      advanceServerStageTo('saving_doc', ev.message || '')
      break
    case 'done':
      uploadProgress.stages.forEach(s => {
        if (s.state !== 'done' && (s.key !== 'saving_doc' || serviceForm.docFile)) {
          s.state = 'done'
        } else if (s.state !== 'done' && s.key === 'saving_doc') {
          s.state = 'pending'
        }
      })
      uploadProgress.serverPct = 100
      uploadProgress.serverStatus = 'success'
      uploadProgress.success = true
      uploadProgress.finished = true
      break
    case 'error':
      uploadProgress.errorMessage = ev.message || 'unknown error'
      uploadProgress.errorStage = ev.stage || ''
      uploadProgress.serverStatus = 'exception'
      uploadProgress.uploadStatus = uploadProgress.uploadPct >= 100 ? '' : 'exception'
      // 把当前 active 的阶段置为 error
      const active = uploadProgress.stages.find(s => s.state === 'active')
      if (active) active.state = 'error'
      else if (ev.stage) setStageState(ev.stage, 'error')
      uploadProgress.finished = true
      break
    default:
      // 未知事件类型直接忽略
      break
  }
}

const uploadWithProgress = (formData) => {
  // 重置进度状态
  uploadProgress.title = 'deploy service'
  uploadProgress.finished = false
  uploadProgress.success = false
  uploadProgress.uploadPct = 0
  uploadProgress.uploadStatus = ''
  uploadProgress.uploadedBytes = 0
  uploadProgress.totalBytes = 0
  uploadProgress.uploadSpeed = 0
  uploadProgress.serverPct = 0
  uploadProgress.serverStatus = ''
  uploadProgress.serverIndeterminate = false
  uploadProgress.errorMessage = ''
  uploadProgress.errorStage = ''
  initStages()
  uploadProgress.visible = true

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    currentXhr = xhr
    xhr.open('POST', '/admin-api/api/v1/custom-services/upload', true)
    xhr.responseType = 'text'
    xhr.timeout = 0  // 不超时（由用户主动取消）

    let buffer = ''
    let consumed = 0  // responseText 中已消费的字符数
    lastProgressTime = Date.now()
    lastProgressBytes = 0

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return
      uploadProgress.uploadedBytes = e.loaded
      uploadProgress.totalBytes = e.total
      uploadProgress.uploadPct = Math.min(100, Math.round((e.loaded / e.total) * 100))
      const now = Date.now()
      const dt = (now - lastProgressTime) / 1000
      if (dt >= 0.5) {
        const dB = e.loaded - lastProgressBytes
        uploadProgress.uploadSpeed = Math.round(dB / dt)
        lastProgressTime = now
        lastProgressBytes = e.loaded
      }
    }
    xhr.upload.onload = () => {
      uploadProgress.uploadPct = 100
      uploadProgress.uploadStatus = 'success'
      // 上传完了，但服务器还在处理，给一个不确定动画
      if (!uploadProgress.finished) uploadProgress.serverIndeterminate = true
    }
    xhr.upload.onerror = () => {
      uploadProgress.uploadStatus = 'exception'
    }

    const drainBuffer = () => {
      const text = xhr.responseText || ''
      if (text.length <= consumed) return
      const fresh = text.slice(consumed)
      consumed = text.length
      buffer += fresh
      let idx
      while ((idx = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, idx).trim()
        buffer = buffer.slice(idx + 1)
        if (!line) continue
        try {
          const ev = JSON.parse(line)
          handleEvent(ev)
        } catch (e) {
          console.warn('Bad NDJSON line:', line, e)
        }
      }
    }

    xhr.onreadystatechange = () => {
      if (xhr.readyState === 3) {
        // 部分响应数据可读
        try { drainBuffer() } catch (e) { console.error(e) }
      } else if (xhr.readyState === 4) {
        try { drainBuffer() } catch (e) { console.error(e) }
        currentXhr = null
        if (xhr.status === 0) {
          // 用户主动取消或网络中断
          if (!uploadProgress.errorMessage) {
            uploadProgress.errorMessage = 'cancelled or network interrupted'
            uploadProgress.serverStatus = 'exception'
            uploadProgress.uploadStatus = 'exception'
            const active = uploadProgress.stages.find(s => s.state === 'active')
            if (active) active.state = 'error'
            uploadProgress.finished = true
          }
          reject(Object.assign(new Error(uploadProgress.errorMessage), { isUploadFailure: true }))
          return
        }
        if (xhr.status >= 400) {
          // 后端在还没开始流式响应前就报错（比如 502/504）
          if (!uploadProgress.errorMessage) {
            uploadProgress.errorMessage =
              `server returned ${xhr.status} ${xhr.statusText || ''}`.trim()
            uploadProgress.serverStatus = 'exception'
            uploadProgress.finished = true
          }
          reject(Object.assign(new Error(uploadProgress.errorMessage), { isUploadFailure: true }))
          return
        }
        // 200，但要看最后一个事件
        if (uploadProgress.errorMessage) {
          reject(Object.assign(new Error(uploadProgress.errorMessage), { isUploadFailure: true }))
        } else if (uploadProgress.success) {
          resolve()
        } else {
          // 流结束但既没 done 也没 error，标记失败
          uploadProgress.errorMessage = 'response ended without done or error event'
          uploadProgress.serverStatus = 'exception'
          uploadProgress.finished = true
          reject(Object.assign(new Error(uploadProgress.errorMessage), { isUploadFailure: true }))
        }
      }
    }

    xhr.onerror = () => {
      uploadProgress.errorMessage = 'network request failed'
      uploadProgress.serverStatus = 'exception'
      uploadProgress.uploadStatus = 'exception'
      uploadProgress.finished = true
    }

    xhr.send(formData)
  })
}

const cancelUpload = async () => {
  try {
    await ElMessageBox.confirm(
      'cancel upload? bytes already sent to the server will be discarded.',
      'cancel upload',
      { type: 'warning', confirmButtonText: 'cancel upload', cancelButtonText: 'keep waiting' },
    )
  } catch { return }
  if (currentXhr) {
    try { currentXhr.abort() } catch {}
  }
}

const closeUploadDialog = () => {
  uploadProgress.visible = false
}

const editService = async (service) => {
  editingService.value = service
  serviceForm.name = service.name
  serviceForm.description = service.description
  serviceForm.port = service.port
  // endpoint已移除，现在通过端口直接访问
  // 从服务信息中读取容器端口，如果没有则使用宿主机端口
  serviceForm.container_port = service.container_port || service.port
  previousPort = service.port  // 更新previousPort，避免watch触发
  serviceForm.memory_limit_mb = service.memory_limit_mb ?? null
  serviceForm.memory_reservation_mb = service.memory_reservation_mb ?? null
  serviceForm.icon = service.icon || 'Box'
  serviceForm.file = null
  
  // 加载现有环境变量配置
  try {
    const response = await axios.get(`/admin-api/api/v1/custom-services/${service.name}/env`)
    const envVarsObj = response.data.env_vars || {}
    
    if (Object.keys(envVarsObj).length > 0) {
      // 转换为表单格式
      envVars.value = Object.keys(envVarsObj).map(key => ({
        key: key,
        value: envVarsObj[key]
      }))
      // 转换为JSON格式
      envVarsJson.value = JSON.stringify(envVarsObj, null, 2)
      envTabType.value = 'json' // 默认显示JSON模式
    } else {
      // 如果没有环境变量，清空（但不显示错误，因为可能确实没有配置）
      envVars.value = []
      envVarsJson.value = ''
      console.log('no env vars configured for this service')
    }
  } catch (error) {
    console.error('failed to load env vars:', error)
    // 如果API调用失败（404等），说明可能没有.env文件，这是正常的
    if (error.response?.status === 404) {
      // 404表示没有配置文件，这是正常的，清空即可
      envVars.value = []
      envVarsJson.value = ''
    } else {
      console.warn('error loading env vars:', error.message)
      envVars.value = []
      envVarsJson.value = ''
    }
  }
  
  // 加载现有卷挂载配置
  try {
    const response = await axios.get(`/admin-api/api/v1/custom-services/${service.name}/volumes`)
    const volumesArray = response.data.volumes || []
    
    if (volumesArray.length > 0) {
      // 转换为表单格式
      volumesList.value = volumesArray.map(volume => {
        const parts = volume.split(':')
        const hostPath = parts[0] || ''
        const containerPath = parts[1] || ''
        const readOnly = parts[2] === 'ro'
        return { hostPath, containerPath, readOnly }
      })
      // 转换为JSON格式
      volumesJson.value = JSON.stringify(volumesArray, null, 2)
      volumesTabType.value = 'json' // 默认显示JSON模式
    } else {
      // 如果没有卷挂载，清空
      volumesList.value = []
      volumesJson.value = ''
      console.log('no volumes configured for this service')
    }
  } catch (error) {
    console.error('failed to load volumes:', error)
    // 如果API调用失败（404等），说明可能没有配置，这是正常的
    if (error.response?.status === 404) {
      volumesList.value = []
      volumesJson.value = ''
    } else {
      console.warn('error loading volumes:', error.message)
      volumesList.value = []
      volumesJson.value = ''
    }
  }
  
  showAddDialog.value = true
}

const showServiceDetails = async (service) => {
  selectedService.value = service
  showDetailsDialog.value = true
  await loadServiceLogs()
}

const handleDetailsDialogClose = () => {
  selectedService.value = null
  serviceLogs.value = ''
  logTail.value = 100
}

const loadServiceLogs = async () => {
  if (!selectedService.value) return
  
  logsLoading.value = true
  try {
    // 自定义服务的容器名是 arbore-{service_name}
    const containerName = `arbore-${selectedService.value.name}`
    const response = await axios.get(`/admin-api/api/v1/services/${containerName}/logs`, {
      params: {
        tail: logTail.value
      }
    })
    
    // Docker tail 返回的是「最后 N 行」但仍为时间正序（旧→新）；界面按倒序展示，最新在上
    const lines = response.data.logs
    if (Array.isArray(lines) && lines.length > 0) {
      serviceLogs.value = [...lines].reverse().join('\n')
    } else {
      serviceLogs.value = 'no logs'
    }
  } catch (error) {
    console.error('failed to load logs:', error)
    const errorMsg = error.response?.data?.detail || error.message || 'unknown error'
    serviceLogs.value = `failed to load logs: ${errorMsg}`
    ElMessage.error('failed to load logs: ' + errorMsg)
  } finally {
    logsLoading.value = false
  }
}

const restartService = async (service) => {
  try {
    await ElMessageBox.confirm(
      `restart service "${service.name}"?\n\nthe container will be re-created and restarted so updated env vars / volumes take effect.`,
      'confirm restart',
      {
        confirmButtonText: 'restart',
        cancelButtonText: 'cancel',
        type: 'warning',
      },
    )

    console.log(`restarting service: ${service.name}`)
    const response = await axios.post(`/admin-api/api/v1/custom-services/${service.name}/restart`)
    console.log('restart response:', response.data)

    ElMessage.success('service restarted')
    await refreshServices()
    if (showDetailsDialog.value && selectedService.value?.name === service.name) {
      await loadServiceLogs()
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('failed to restart service:', error)
      const errorMsg = error.response?.data?.detail || error.message || 'unknown error'
      ElMessage.error('failed to restart service: ' + errorMsg)
    }
  }
}

const deleteService = async (service) => {
  try {
    await ElMessageBox.confirm(
      `delete service "${service.name}"? the container will be stopped and removed, and the entry deleted from config.`,
      'confirm delete',
      {
        confirmButtonText: 'delete',
        cancelButtonText: 'cancel',
        type: 'warning',
      },
    )

    console.log(`deleting service: ${service.name}`)
    const response = await axios.delete(`/admin-api/api/v1/custom-services/${service.name}`)
    console.log('delete response:', response.data)

    if (response.data.warnings && response.data.warnings.length > 0) {
      ElMessage.warning(`service deleted with warnings: ${response.data.warnings.join('; ')}`)
    } else {
      ElMessage.success('service deleted')
    }
    await refreshServices()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('failed to delete service:', error)
      const errorMsg = error.response?.data?.detail || error.message || 'unknown error'
      ElMessage.error('failed to delete service: ' + errorMsg)
    }
  }
}

const resetForm = () => {
  editingService.value = null
  serviceForm.name = ''
  serviceForm.description = ''
  serviceForm.port = 7000  // 默认7000
  serviceForm.container_port = 7000  // 默认等于宿主机端口
  serviceForm.memory_limit_mb = null
  serviceForm.memory_reservation_mb = null
  previousPort = 7000  // 重置previousPort
  // endpoint已移除，现在通过端口直接访问
  serviceForm.icon = 'Box'  // 重置为默认图标
  serviceForm.file = null
  serviceForm.docFile = null
  // 重置环境变量
  envVars.value = []
  envVarsJson.value = ''
  envTabType.value = 'form'
  // 重置卷挂载
  volumesList.value = []
  volumesJson.value = ''
  volumesTabType.value = 'form'
  // 清空文件输入（使用原生方式）
  const fileInput = document.getElementById('file-input-tar')
  if (fileInput) {
    fileInput.value = ''
  }
  const docInput = document.getElementById('file-input-doc')
  if (docInput) {
    docInput.value = ''
  }
  if (serviceFormRef.value) {
    serviceFormRef.value.resetFields()
  }
}

// 监听对话框关闭，重置表单
const handleDialogClose = () => {
  resetForm()
}

// Hook into the global TUI shell shortcuts so pressing `r` refreshes this tab.
// We deliberately do not register a search hook here yet because the existing
// page already has its own filter input; revisit if that input gets a ref.
onMounted(() => {
  refreshServices()
  if (registerRefresh) registerRefresh(TAB_NAME, refreshServices)
})
onBeforeUnmount(() => {
  if (unregisterRefresh) unregisterRefresh(TAB_NAME)
  if (unregisterSearch)  unregisterSearch(TAB_NAME)
})
</script>

<style scoped>
/* Custom services view - tuned to match the global Catppuccin Mocha theme.
   Most heavy lifting is done by the global Element Plus variable overrides
   in src/styles/arbore-theme.css; rules here only touch the few page-level
   tokens that don't have a global equivalent. */
.custom-services-view {
  padding: 0;
  font-family: var(--font-mono);
  color: var(--fg-text);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
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

.services-card {
  background: var(--bg-mantle);
  border: 1px solid var(--border);
  border-radius: var(--radius-tile);
}

.services-card :deep(.el-card__header) {
  background: var(--bg-base);
  border-bottom: 1px solid var(--border);
  padding: 12px 16px;
}

.services-card :deep(.el-card__body) {
  padding: 16px;
  background: transparent;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--fg-text);
  font-weight: 500;
}
.card-title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--accent);
  font-weight: 600;
}

.cs-mono {
  font-family: var(--font-mono);
  color: var(--fg-text);
  font-size: 12.5px;
}

.cs-id {
  margin-top: 4px;
  font-size: 11px;
  color: var(--fg-muted);
  font-family: var(--font-mono);
}

.text-muted { color: var(--fg-muted); }

.service-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.service-icon {
  color: var(--accent);
  font-size: 16px;
}

.description-text {
  color: var(--fg-muted);
  font-size: 12px;
}

.form-tip {
  font-size: 11.5px;
  color: var(--fg-muted);
  margin-top: 4px;
  background: transparent;
  padding: 0;
  user-select: text;
  -webkit-user-select: text;
  -moz-user-select: text;
  -ms-user-select: text;
}

.form-error {
  font-size: 11.5px;
  color: var(--mocha-red);
  margin-top: 4px;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 对话框底部按钮样式 */
:deep(.el-dialog__footer) {
  background: rgba(30, 41, 59, 0.95);
  border-top: 1px solid rgba(148, 163, 184, 0.1);
  padding: 20px;
}

:deep(.el-dialog__footer .el-button) {
  background: transparent;
  border-color: rgba(148, 163, 184, 0.3);
  color: #94a3b8;
}

:deep(.el-dialog__footer .el-button:hover) {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(148, 163, 184, 0.5);
  color: #f1f5f9;
}

:deep(.el-dialog__footer .el-button--primary) {
  background: rgba(16, 185, 129, 0.2);
  border-color: #10b981;
  color: #10b981;
}

:deep(.el-dialog__footer .el-button--primary:hover) {
  background: rgba(16, 185, 129, 0.3);
  border-color: #10b981;
  color: #10b981;
}

/* 表格样式 */
.services-card :deep(.el-table) {
  background: transparent;
  color: #f1f5f9;
}

.services-card :deep(.el-table th) {
  background: rgba(15, 23, 42, 0.5);
  color: #94a3b8;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.services-card :deep(.el-table td) {
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.services-card :deep(.el-table tr) {
  background: transparent;
}

.services-card :deep(.el-table--striped .el-table__body tr.el-table__row--striped td) {
  background: rgba(15, 23, 42, 0.3);
}

.services-card :deep(.el-table--striped .el-table__body tr.el-table__row--striped:hover td) {
  background: rgba(15, 23, 42, 0.5);
}

.services-card :deep(.el-table__body tr:hover > td) {
  background: rgba(15, 23, 42, 0.5);
}

/* 对话框样式 */
:deep(.el-dialog) {
  background: rgba(30, 41, 59, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.1);
}

:deep(.el-dialog__header) {
  background: transparent;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  color: #f1f5f9;
  padding: 20px 20px 16px 20px;
}

:deep(.el-dialog__body) {
  background: rgba(30, 41, 59, 0.95);
  color: #f1f5f9;
  padding: 20px;
}

:deep(.el-alert) {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.2);
}

:deep(.el-alert__content) {
  color: #94a3b8;
}

.alert-text {
  color: #94a3b8;
  user-select: text;
  -webkit-user-select: text;
  -moz-user-select: text;
  -ms-user-select: text;
}

:deep(.el-form-item__label) {
  color: #94a3b8;
}

:deep(.el-input__inner),
:deep(.el-textarea__inner) {
  background: rgba(15, 23, 42, 0.5);
  border-color: rgba(148, 163, 184, 0.2);
  color: #f1f5f9;
}

:deep(.el-input__inner:focus),
:deep(.el-textarea__inner:focus) {
  border-color: #10b981;
}

.file-upload-wrapper {
  width: 100%;
}

.file-input-label {
  display: inline-block;
  cursor: pointer;
  position: relative;
  z-index: 1;
}

.file-input-label .el-button {
  pointer-events: none;
}

.file-name {
  margin-top: 8px;
  color: #10b981;
  font-size: 14px;
}

/* 环境变量配置样式 */
.env-vars-tabs {
  width: 100%;
}

.env-vars-form {
  width: 100%;
}

.env-var-item {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.env-var-item:last-child {
  margin-bottom: 0;
}

.env-vars-json-input {
  width: 100%;
}

.env-vars-json-input :deep(.el-textarea__inner) {
  font-family: 'Courier New', monospace;
  font-size: 13px;
}

.service-icon-cell {
  display: flex;
  justify-content: center;
  align-items: center;
}

.service-icon {
  color: #10b981;
  font-size: 24px;
}

/* 图标选择器样式 */
.icon-selector-wrapper {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.icon-selector-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: rgba(15, 23, 42, 0.5);
  border-color: rgba(148, 163, 184, 0.3);
  color: #94a3b8;
}

.icon-selector-trigger:hover {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(148, 163, 184, 0.5);
  color: #f1f5f9;
}

.icon-trigger-icon {
  font-size: 18px;
  color: #10b981;
}

.icon-trigger-text {
  color: #94a3b8;
}

/* 图标选择弹窗 */
:deep(.icon-selector-dialog .el-dialog__header) {
  background: transparent;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  padding: 16px 20px;
}

:deep(.icon-selector-dialog .el-dialog__body) {
  padding: 20px;
  background: rgba(30, 41, 59, 0.95);
}

.icon-selector-search {
  margin-bottom: 16px;
}

.icon-selector-grid {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 8px;
  max-height: 500px;
  overflow-y: auto;
  padding: 8px;
  background: rgba(15, 23, 42, 0.5);
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.icon-grid-item {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  padding: 8px;
  border-radius: 6px;
  border: 2px solid transparent;
  background: rgba(30, 41, 59, 0.5);
  cursor: pointer;
  transition: all 0.2s;
  aspect-ratio: 1;
}

.icon-grid-item:hover {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(16, 185, 129, 0.3);
  transform: scale(1.1);
}

.icon-grid-item.active {
  background: rgba(16, 185, 129, 0.2);
  border-color: #10b981;
}

.icon-grid-icon {
  font-size: 24px;
  color: #10b981;
}

.icon-preview-container {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px;
  background: rgba(15, 23, 42, 0.5);
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.icon-preview-large {
  font-size: 48px;
  color: #10b981;
}

.icon-preview-name {
  font-size: 12px;
  color: #94a3b8;
}

.status-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.service-details {
  color: #f1f5f9;
}

.logs-section {
  margin-top: 20px;
}

.logs-header h3 {
  margin: 0;
  color: #f1f5f9;
  font-size: 16px;
}

.logs-container {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 6px;
  padding: 12px;
}

.logs-content {
  margin: 0;
  padding: 0;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #94a3b8;
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* ----------------------------------------------------------------------------
   Upload progress dialog (dark theme)
   ---------------------------------------------------------------------------- */
.upload-progress-dialog :deep(.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(148, 163, 184, 0.18);
}
.upload-progress-dialog :deep(.el-dialog__header) {
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  margin: 0;
  padding: 18px 24px;
}
.upload-progress-dialog :deep(.el-dialog__title) { color: #f1f5f9; font-weight: 600; }
.upload-progress-dialog :deep(.el-dialog__body) { padding: 20px 24px; }
.upload-progress-dialog :deep(.el-dialog__footer) {
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  padding: 14px 24px;
}

.upload-progress-body { color: #e2e8f0; }

.up-section {
  background: rgba(15, 23, 42, 0.55);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.up-section:last-child { margin-bottom: 0; }

.up-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.up-section-title {
  font-size: 13px;
  color: #cbd5e1;
  font-weight: 500;
}
.up-section-pct {
  font-size: 13px;
  color: #10b981;
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}

.up-section-meta {
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}
.up-speed { color: #60a5fa; margin-left: 6px; }

.up-stages {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.up-stage-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  font-size: 12.5px;
  color: #94a3b8;
  border-radius: 4px;
  transition: all 0.2s ease;
}
.up-stage-row.stage-active {
  color: #10b981;
  background: rgba(16, 185, 129, 0.08);
}
.up-stage-row.stage-done { color: #34d399; }
.up-stage-row.stage-error {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
}
.up-stage-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
.up-stage-row.stage-active .up-stage-icon {
  animation: arbore-spin 1.2s linear infinite;
}
@keyframes arbore-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.up-stage-label { flex-shrink: 0; }
.up-stage-msg {
  margin-left: auto;
  font-size: 11.5px;
  color: #64748b;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}

</style>

