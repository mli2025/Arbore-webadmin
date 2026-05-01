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
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-title">
        <h2>自定义服务管理</h2>
        <p class="header-desc">管理您的自定义API服务，支持上传Docker镜像并自动配置</p>
      </div>
      <el-button type="primary" @click="onAddServiceClick">
        <Plus style="margin-right: 4px;" />
        添加服务
      </el-button>
    </div>

    <!-- 服务列表 -->
    <el-card class="services-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>服务列表</span>
          <el-button link @click="refreshServices" :loading="loading">
            <Refresh style="margin-right: 4px;" />
            刷新
          </el-button>
        </div>
      </template>

      <el-table
        :data="services"
        v-loading="loading"
        stripe
        style="width: 100%"
        :empty-text="loading ? '加载中...' : '暂无自定义服务'"
      >
        <el-table-column label="图标" width="80" align="center">
          <template #default="{ row }">
            <div class="service-icon-cell">
              <component 
                :is="getIconComponent(row.icon || 'Box')" 
                class="service-icon"
                :style="{ fontSize: '24px', color: '#10b981' }"
              />
            </div>
          </template>
        </el-table-column>
        
        <el-table-column prop="name" label="服务名称" width="180">
          <template #default="{ row }">
            <span>{{ row.name }}</span>
          </template>
        </el-table-column>
        
        <el-table-column prop="description" label="描述" min-width="200">
          <template #default="{ row }">
            <span class="description-text">{{ row.description || '无描述' }}</span>
          </template>
        </el-table-column>
        
        <el-table-column prop="port" label="端口" width="120" align="center">
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ row.port }}</el-tag>
          </template>
        </el-table-column>
        
        <el-table-column label="容器状态" width="150" align="center">
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
              <div v-if="row.container_id" style="margin-top: 4px; font-size: 11px; color: #909399;">
                ID: {{ row.container_id }}
              </div>
            </div>
          </template>
        </el-table-column>
        
        <el-table-column label="访问地址" width="250">
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
        
        <el-table-column label="操作" width="350" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              link
              type="info"
              size="small"
              @click="showServiceDetails(row)"
            >
              详情
            </el-button>
            <el-button
              v-if="row.has_doc"
              link
              type="success"
              size="small"
              @click="viewServiceDoc(row)"
            >
              文档
            </el-button>
            <el-button
              link
              type="primary"
              size="small"
              @click="editService(row)"
            >
              编辑
            </el-button>
            <el-button
              link
              type="warning"
              size="small"
              @click="restartService(row)"
            >
              重启
            </el-button>
            <el-button
              link
              type="danger"
              size="small"
              @click="deleteService(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 服务详情对话框 -->
    <el-dialog
      v-model="showDetailsDialog"
      title="服务详情"
      width="80%"
      :close-on-click-modal="false"
      @close="handleDetailsDialogClose"
    >
      <div v-if="selectedService" class="service-details">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="服务名称">{{ selectedService.name }}</el-descriptions-item>
          <el-descriptions-item label="端口">{{ selectedService.port }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ selectedService.description }}</el-descriptions-item>
          <el-descriptions-item label="容器状态">
            <el-tag :type="getStatusType(selectedService.status)" size="small">
              {{ getStatusText(selectedService.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="健康状态" v-if="selectedService.health && selectedService.health !== 'unknown'">
            <el-tag 
              :type="selectedService.health === 'healthy' ? 'success' : (selectedService.health === 'unhealthy' ? 'danger' : 'warning')" 
              size="small"
            >
              {{ getHealthText(selectedService.health, selectedService.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="容器ID" v-if="selectedService.container_id">
            {{ selectedService.container_id }}
          </el-descriptions-item>
          <el-descriptions-item label="访问地址" :span="2">
            <el-link :href="getServiceUrl(selectedService)" target="_blank" type="primary">
              {{ getServiceUrl(selectedService) }}
            </el-link>
          </el-descriptions-item>
          <el-descriptions-item label="说明文档" :span="2">
            <template v-if="selectedService.has_doc">
              <el-button type="primary" size="small" @click="viewServiceDoc(selectedService)">
                查看PDF文档
              </el-button>
            </template>
            <span v-else style="color: #909399;">未上传</span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="logs-section" style="margin-top: 20px;">
          <div class="logs-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h3>容器日志</h3>
            <div>
              <el-select v-model="logTail" size="small" style="width: 120px; margin-right: 10px;" @change="loadServiceLogs">
                <el-option label="最近100行" :value="100" />
                <el-option label="最近500行" :value="500" />
                <el-option label="最近1000行" :value="1000" />
              </el-select>
              <el-button size="small" @click="loadServiceLogs" :loading="logsLoading">
                <Refresh style="margin-right: 4px;" />
                刷新
              </el-button>
            </div>
          </div>
          <el-scrollbar height="400px" class="logs-container">
            <pre class="logs-content">{{ serviceLogs }}</pre>
          </el-scrollbar>
        </div>
      </div>
    </el-dialog>

    <!-- 添加/编辑服务对话框 -->
    <el-dialog
      v-model="showAddDialog"
      :title="editingService ? '编辑服务' : '添加服务'"
      width="600px"
      :close-on-click-modal="false"
      @close="handleDialogClose"
    >
      <el-form
        ref="serviceFormRef"
        :model="serviceForm"
        :rules="formRules"
        label-width="100px"
        label-position="left"
      >
        <el-form-item label="服务图标" prop="icon">
          <div class="icon-selector-wrapper">
            <el-button 
              class="icon-selector-trigger"
              @click="showIconSelector = true"
            >
              <component 
                :is="getIconComponent(serviceForm.icon)" 
                class="icon-trigger-icon"
              />
              <span class="icon-trigger-text">选择图标</span>
            </el-button>
            <div class="icon-preview-container">
              <component 
                :is="getIconComponent(serviceForm.icon)" 
                class="icon-preview-large"
              />
              <span class="icon-preview-name">{{ getIconLabel(serviceForm.icon) }}</span>
            </div>
          </div>
          
          <!-- 图标选择弹窗 -->
          <el-dialog
            v-model="showIconSelector"
            title="选择图标"
            width="800px"
            :close-on-click-modal="true"
            class="icon-selector-dialog"
          >
            <div class="icon-selector-search">
              <el-input
                v-model="iconSearchText"
                placeholder="搜索图标..."
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

        <el-form-item label="服务名称" prop="name">
          <el-input
            v-model="serviceForm.name"
            placeholder="例如: my-api-service"
            :disabled="!!editingService"
            @blur="handleNameBlur"
          />
          <div class="form-tip">只能包含小写字母、数字和连字符</div>
        </el-form-item>

        <el-form-item label="描述信息" prop="description">
          <el-input
            v-model="serviceForm.description"
            type="textarea"
            :rows="2"
            placeholder="请输入服务描述"
          />
        </el-form-item>

        <el-form-item label="宿主机端口" prop="port">
          <el-input-number
            v-model="serviceForm.port"
            :min="7000"
            :max="7999"
            :step="1"
            style="width: 100%"
          />
          <div class="form-tip">端口范围：7000-7999，这是对外访问的端口（格式：http://服务器IP:端口）</div>
        </el-form-item>

        <el-form-item label="容器内端口" prop="container_port">
          <el-input-number
            v-model="serviceForm.container_port"
            :min="1"
            :max="65535"
            :step="1"
            style="width: 100%"
          />
          <div class="form-tip">容器内服务实际监听的端口，默认与宿主机端口一致。如果服务硬编码了端口（如8000），可以修改为实际端口，系统会自动映射到宿主机端口</div>
        </el-form-item>

        <el-form-item label="内存限制 (MB)" prop="memory_limit_mb">
          <el-input-number
            v-model="serviceForm.memory_limit_mb"
            :min="0"
            :max="65536"
            :step="256"
            style="width: 100%"
            placeholder="不填则不限制"
            controls-position="right"
          />
          <div class="form-tip">容器最大可用内存（MB），如 4096 表示 4GB。修改后需重启容器生效</div>
        </el-form-item>
        <el-form-item label="内存预留 (MB)" prop="memory_reservation_mb">
          <el-input-number
            v-model="serviceForm.memory_reservation_mb"
            :min="0"
            :max="65536"
            :step="256"
            style="width: 100%"
            placeholder="可选"
            controls-position="right"
          />
          <div class="form-tip">容器保证可用内存（MB），可选。修改后需重启容器生效</div>
        </el-form-item>

        <el-form-item
          v-if="!editingService"
          label="Docker镜像"
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
                选择tar文件
              </el-button>
            </label>
            <div v-if="serviceForm.file" class="file-name">
              {{ serviceForm.file.name }}
            </div>
            <div class="form-tip">
              请上传已打包的Docker镜像tar文件
            </div>
          </div>
        </el-form-item>

        <!-- 说明文档上传 -->
        <el-form-item label="说明文档">
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
                选择PDF文件
              </el-button>
            </label>
            <div v-if="serviceForm.docFile" class="file-name">
              {{ serviceForm.docFile.name }}
              <el-button link type="danger" size="small" @click="removeDocFile" style="margin-left: 8px;">移除</el-button>
            </div>
            <div v-else-if="editingService && editingService.has_doc" class="file-name">
              <el-tag type="success" size="small">已有文档</el-tag>
              <el-button link type="primary" size="small" @click="viewServiceDoc(editingService)" style="margin-left: 8px;">查看</el-button>
              <el-button link type="danger" size="small" @click="deleteServiceDoc(editingService)" style="margin-left: 4px;">删除文档</el-button>
            </div>
            <div class="form-tip">
              可选，上传PDF格式的服务说明文档，方便后续查看
            </div>
          </div>
        </el-form-item>

        <!-- 环境变量配置 -->
        <el-form-item
          label="环境变量"
        >
          <el-tabs v-model="envTabType" class="env-vars-tabs">
            <el-tab-pane label="表单模式" name="form">
              <div class="env-vars-form">
                <div
                  v-for="(item, index) in envVars"
                  :key="index"
                  class="env-var-item"
                >
                  <el-input
                    v-model="item.key"
                    placeholder="变量名"
                    style="width: 200px; margin-right: 8px;"
                  />
                  <el-input
                    v-model="item.value"
                    placeholder="变量值"
                    type="password"
                    show-password
                    style="flex: 1; margin-right: 8px;"
                  />
                  <el-button
                    type="danger"
                    link
                    @click="removeEnvVar(index)"
                  >
                    删除
                  </el-button>
                </div>
                <el-button
                  type="primary"
                  link
                  @click="addEnvVar"
                  style="margin-top: 8px;"
                >
                  + 添加变量
                </el-button>
              </div>
            </el-tab-pane>
            <el-tab-pane label="JSON模式" name="json">
              <el-input
                v-model="envVarsJson"
                type="textarea"
                :rows="8"
                placeholder='{"AUTH_ENABLED": "true", "SM4_KEY": "your_key"}'
                class="env-vars-json-input"
              />
              <div class="form-tip">
                请输入JSON格式的环境变量配置，例如: {"KEY1": "value1", "KEY2": "value2"}
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-form-item>

        <!-- 卷挂载配置 -->
        <el-form-item
          label="卷挂载"
        >
          <el-tabs v-model="volumesTabType" class="env-vars-tabs">
            <el-tab-pane label="表单模式" name="form">
              <div class="env-vars-form">
                <div
                  v-for="(item, index) in volumesList"
                  :key="index"
                  class="env-var-item"
                >
                  <el-input
                    v-model="item.hostPath"
                    placeholder="宿主机路径（如: /path/to/huggingface/models）"
                    style="flex: 1; margin-right: 8px;"
                  />
                  <el-input
                    v-model="item.containerPath"
                    placeholder="容器内路径（如: /models）"
                    style="flex: 1; margin-right: 8px;"
                  />
                  <el-checkbox
                    v-model="item.readOnly"
                    style="margin-right: 8px;"
                  >
                    只读
                  </el-checkbox>
                  <el-button
                    type="danger"
                    link
                    @click="removeVolume(index)"
                  >
                    删除
                  </el-button>
                </div>
                <el-button
                  type="primary"
                  link
                  @click="addVolume"
                  style="margin-top: 8px;"
                >
                  + 添加挂载
                </el-button>
              </div>
            </el-tab-pane>
            <el-tab-pane label="JSON模式" name="json">
              <el-input
                v-model="volumesJson"
                type="textarea"
                :rows="6"
                placeholder='["/path/to/huggingface/models:/models", "/path/to/data:/data:ro"]'
                class="env-vars-json-input"
              />
              <div class="form-tip">
                请输入JSON数组格式的卷挂载配置，例如: ["/host/path:/container/path", "/host/path2:/container/path2:ro"]
                <br>
                格式说明：每个挂载项为字符串，格式为 "宿主机路径:容器内路径" 或 "宿主机路径:容器内路径:ro"（ro表示只读）
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-form-item>

        <el-form-item v-if="!editingService">
          <el-alert
            type="info"
            :closable="false"
            show-icon
          >
            <template #default>
              <span class="alert-text">自定义服务内部端口范围：7000-7999，通过nginx路径区分不同服务，nginx统一对外提供访问</span>
            </template>
          </el-alert>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="showAddDialog = false">取消</el-button>
          <el-button
            type="primary"
            @click="submitService"
            :loading="submitting"
          >
            {{ editingService ? '更新' : '部署' }}
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
            <span class="up-section-title">浏览器 → 服务器（上传镜像）</span>
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
            <span class="up-section-title">服务器处理</span>
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
          :title="'部署失败' + (uploadProgress.errorStage ? '（阶段：' + stageLabelOf(uploadProgress.errorStage) + '）' : '')"
          :description="uploadProgress.errorMessage"
          style="margin-top: 14px;"
        />

        <el-alert
          v-if="uploadProgress.success"
          type="success"
          :closable="false"
          show-icon
          title="部署成功"
          description="服务已部署并启动，可在列表中查看"
          style="margin-top: 14px;"
        />
      </div>

      <template #footer>
        <el-button
          v-if="!uploadProgress.finished"
          type="danger"
          plain
          @click="cancelUpload"
        >取消上传</el-button>
        <el-button
          v-if="uploadProgress.finished"
          type="primary"
          @click="closeUploadDialog"
        >关闭</el-button>
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
import { ref, reactive, computed, onMounted, nextTick, watch, inject } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const setActiveTab = inject('setActiveTab', null)
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
      throw new Error('环境变量JSON格式错误')
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
        throw new Error('卷挂载配置必须是数组格式')
      }
      return volumesJson.value
    } catch (e) {
      throw new Error('卷挂载JSON格式错误: ' + e.message)
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
    { required: true, message: '请输入服务名称', trigger: 'blur' },
    {
      pattern: /^[a-z0-9-]+$/,
      message: '服务名称只能包含小写字母、数字和连字符',
      trigger: 'blur'
    }
  ],
  description: [
    { required: true, message: '请输入服务描述', trigger: 'blur' }
  ],
  port: [
    { required: true, message: '请输入端口号', trigger: 'blur' },
    {
      type: 'number',
      min: 7000,
      max: 7999,
      message: '端口必须在7000-7999范围内',
      trigger: 'blur'
    }
  ],
  file: [
    {
      validator: (rule, value, callback) => {
        if (!editingService.value && !serviceForm.file) {
          callback(new Error('请选择Docker镜像tar文件'))
        } else {
          callback()
        }
      },
      trigger: 'change'
    }
  ]
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

// 获取状态文本（中文显示）
const getStatusText = (status) => {
  if (!status) return '未知'
  const statusLower = status.toLowerCase()
  const statusMap = {
    'running': '运行中',
    'stopped': '已停止',
    'exited': '已退出',
    'restarting': '重启中',
    'paused': '已暂停',
    'not_found': '未找到',
    'created': '已创建',
    'removing': '删除中'
  }
  return statusMap[statusLower] || status
}

// 获取健康状态文本（中文显示）
const getHealthText = (health, containerStatus) => {
  if (!health) return '未知'
  const healthLower = health.toLowerCase()
  const statusLower = containerStatus ? containerStatus.toLowerCase() : ''
  
  // 如果容器已经运行，健康检查还在starting，显示为"健康检查中"
  if (healthLower === 'starting' && statusLower === 'running') {
    return '健康检查中'
  }
  
  const healthMap = {
    'healthy': '健康',
    'unhealthy': '不健康',
    'starting': '启动中',
    'none': '无检查'
  }
  return healthMap[healthLower] || health
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
    ElMessage.error('获取服务列表失败: ' + (error.response?.data?.detail || error.message))
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
      ElMessage.error('只支持PDF格式的说明文档')
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
    await ElMessageBox.confirm('确定要删除该服务的说明文档吗？', '确认删除', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await axios.delete(`/admin-api/api/v1/custom-services/${service.name}/doc`)
    ElMessage.success('说明文档已删除')
    service.has_doc = false
    if (editingService.value) {
      editingService.value.has_doc = false
    }
    await refreshServices()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除说明文档失败: ' + (error.response?.data?.detail || error.message))
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
    ElMessage.warning('请先完成许可证注册后再添加自定义服务')
    if (typeof setActiveTab === 'function') {
      setActiveTab('license')
    }
  } catch (err) {
    ElMessage.error('验证注册状态失败: ' + (err.response?.data?.detail?.message || err.message))
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
          ElMessage.error(error.message || '环境变量配置错误')
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
          ElMessage.error(error.message || '卷挂载配置错误')
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
            console.error('上传说明文档失败:', docErr)
            ElMessage.warning('服务已更新，但说明文档上传失败')
          }
        }
        
        ElMessage.success('服务更新成功')
      } else {
        // 添加服务
        if (!serviceForm.file) {
          ElMessage.error('请选择Docker镜像tar文件')
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
          let errorMessage = '验证失败'
          if (error.response?.data?.detail) {
            errorMessage = error.response.data.detail
          } else if (error.response) {
            errorMessage = `服务器错误: ${error.response.status} ${error.response.statusText}`
          }
          ElMessage.error('部署服务失败: ' + errorMessage)
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
          console.log('准备发送的环境变量:', envVarsJsonStr)
          if (envVarsJsonStr && envVarsJsonStr.trim()) {
            formData.append('env_vars', envVarsJsonStr)
            console.log('已添加环境变量到FormData')
          } else {
            console.log('环境变量为空，跳过')
          }
        } catch (error) {
          ElMessage.error(error.message || '环境变量配置错误')
          submitting.value = false
          return
        }
        
        // 添加卷挂载配置
        try {
          const volumesJsonStr = getVolumesJson()
          console.log('准备发送的卷挂载:', volumesJsonStr)
          if (volumesJsonStr && volumesJsonStr.trim()) {
            formData.append('volumes', volumesJsonStr)
            console.log('已添加卷挂载到FormData')
          } else {
            console.log('卷挂载为空，跳过')
          }
        } catch (error) {
          ElMessage.error(error.message || '卷挂载配置错误')
          submitting.value = false
          return
        }

        // 添加说明文档
        if (serviceForm.docFile) {
          formData.append('doc_file', serviceForm.docFile)
        }

        // 走流式上传：XHR 发请求，前端解析 NDJSON 事件实时显示进度
        await uploadWithProgress(formData)

        ElMessage.success('服务部署成功')
      }

      showAddDialog.value = false
      resetForm()
      await refreshServices()
    } catch (error) {
      console.error('服务操作失败:', error)
      let errorMessage = '未知错误'

      if (error && error.isUploadFailure) {
        // 流式上传里抛出的错误，已经在弹窗里展示，这里只静默 toast 简短提示
        errorMessage = error.message || '上传失败'
        ElMessage.error('部署服务失败: ' + errorMessage)
        submitting.value = false
        return
      }

      if (error.response) {
        const detail = error.response.data?.detail || error.response.data?.message
        if (detail) {
          errorMessage = detail
        } else {
          errorMessage = `服务器错误: ${error.response.status} ${error.response.statusText}`
        }
      } else if (error.request) {
        errorMessage = '无法连接到服务器，请检查后端服务是否运行'
      } else {
        errorMessage = error.message || '未知错误'
      }

      ElMessage.error(
        (editingService.value ? '更新' : '部署') +
        '服务失败: ' + errorMessage
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
  { key: 'validating',             label: '校验配置' },
  { key: 'uploading_to_portainer', label: '传输到 Portainer 并加载镜像' },
  { key: 'image_loaded',           label: '镜像加载完成', virtual: true },
  { key: 'creating_container',     label: '创建容器' },
  { key: 'starting_container',     label: '启动容器' },
  { key: 'saving_doc',             label: '保存说明文档' },
]

const uploadProgress = reactive({
  visible: false,
  title: '部署服务',
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
      uploadProgress.errorMessage = ev.message || '未知错误'
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
  uploadProgress.title = '部署服务'
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
            uploadProgress.errorMessage = '已取消或网络中断'
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
              `服务器返回 ${xhr.status} ${xhr.statusText || ''}`.trim()
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
          uploadProgress.errorMessage = '响应非法结束（既未完成也未报错）'
          uploadProgress.serverStatus = 'exception'
          uploadProgress.finished = true
          reject(Object.assign(new Error(uploadProgress.errorMessage), { isUploadFailure: true }))
        }
      }
    }

    xhr.onerror = () => {
      uploadProgress.errorMessage = '网络请求失败'
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
      '确定要取消上传吗？已经传输到服务器的内容会丢失。',
      '取消上传',
      { type: 'warning', confirmButtonText: '取消上传', cancelButtonText: '继续等待' },
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
      console.log('该服务未配置环境变量')
    }
  } catch (error) {
    console.error('加载环境变量失败:', error)
    // 如果API调用失败（404等），说明可能没有.env文件，这是正常的
    if (error.response?.status === 404) {
      // 404表示没有配置文件，这是正常的，清空即可
      envVars.value = []
      envVarsJson.value = ''
    } else {
      // 其他错误才提示
      console.warn('加载环境变量时出错:', error.message)
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
      console.log('该服务未配置卷挂载')
    }
  } catch (error) {
    console.error('加载卷挂载失败:', error)
    // 如果API调用失败（404等），说明可能没有配置，这是正常的
    if (error.response?.status === 404) {
      volumesList.value = []
      volumesJson.value = ''
    } else {
      console.warn('加载卷挂载时出错:', error.message)
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
      serviceLogs.value = '暂无日志'
    }
  } catch (error) {
    console.error('加载日志失败:', error)
    const errorMsg = error.response?.data?.detail || error.message || '未知错误'
    serviceLogs.value = `加载日志失败: ${errorMsg}`
    ElMessage.error('加载日志失败: ' + errorMsg)
  } finally {
    logsLoading.value = false
  }
}

const restartService = async (service) => {
  try {
    await ElMessageBox.confirm(
      `确定要重启服务 "${service.name}" 吗？\n\n此操作将重新创建并启动容器，以加载最新的环境变量和配置。`,
      '确认重启容器',
      {
        confirmButtonText: '确定重启',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    console.log(`正在重启服务: ${service.name}`)
    const response = await axios.post(`/admin-api/api/v1/custom-services/${service.name}/restart`)
    console.log('重启服务响应:', response.data)
    
    ElMessage.success('服务重启成功')
    await refreshServices()
    // 如果详情对话框打开，刷新日志
    if (showDetailsDialog.value && selectedService.value?.name === service.name) {
      await loadServiceLogs()
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('重启服务失败:', error)
      const errorMsg = error.response?.data?.detail || error.message || '未知错误'
      ElMessage.error('重启服务失败: ' + errorMsg)
    }
  }
}

const deleteService = async (service) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除服务 "${service.name}" 吗？此操作将停止并删除容器，并从配置中移除。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    console.log(`正在删除服务: ${service.name}`)
    const response = await axios.delete(`/admin-api/api/v1/custom-services/${service.name}`)
    console.log('删除服务响应:', response.data)
    
    if (response.data.warnings && response.data.warnings.length > 0) {
      ElMessage.warning(`服务已删除，但有警告: ${response.data.warnings.join('; ')}`)
    } else {
      ElMessage.success('服务删除成功')
    }
    await refreshServices()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除服务失败:', error)
      const errorMsg = error.response?.data?.detail || error.message || '未知错误'
      ElMessage.error('删除服务失败: ' + errorMsg)
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

onMounted(() => {
  refreshServices()
})
</script>

<style scoped>
.custom-services-view {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  padding: 20px 0;
}

.header-title h2 {
  font-size: 24px;
  font-weight: 600;
  color: #f1f5f9;
  margin: 0 0 8px 0;
}

.header-desc {
  font-size: 14px;
  color: #94a3b8;
  margin: 0;
}

.services-card {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 8px;
}

.services-card :deep(.el-card__header) {
  background: rgba(15, 23, 42, 0.5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  padding: 16px 20px;
}

.services-card :deep(.el-card__body) {
  padding: 20px;
  background: rgba(30, 41, 59, 0.3);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #f1f5f9;
  font-weight: 500;
}

.service-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.service-icon {
  color: #10b981;
  font-size: 16px;
}

.description-text {
  color: #94a3b8;
}

.form-tip {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  background: transparent;
  padding: 0;
  user-select: text;
  -webkit-user-select: text;
  -moz-user-select: text;
  -ms-user-select: text;
}

.form-error {
  font-size: 12px;
  color: #f56565;
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

