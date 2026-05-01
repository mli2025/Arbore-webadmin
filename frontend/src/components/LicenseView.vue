<template>
  <!--
    许可证管理视图 / License Management View

    中文说明（仅注释）:
    本组件展示宿主机硬件指纹、当前许可证状态，并提供注册表单。
    UI 文案统一使用英文，避免在不同字体下显示效果不一致。
    "复制" 按钮原先用 plain 模式在暗色主题下文字难以辨认，已改为
    实心 primary 按钮。
  -->
  <div class="license-view">
    <div class="page-header">
      <div class="header-title">
        <h2>license</h2>
        <p class="header-desc">
          Register and validate the Arbore AI Host license.
          The host fingerprint is bound to this physical machine.
        </p>
      </div>
    </div>

    <el-card class="license-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>registration status</span>
          <el-tag v-if="license.registered" type="success" size="small">registered</el-tag>
          <el-tag v-else type="info" size="small">not registered</el-tag>
        </div>
      </template>

      <div v-if="license.registered" class="status-section">
        <el-descriptions :column="1" border class="arbore-descriptions">
          <el-descriptions-item label="company name">{{ license.companyName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="company id">{{ license.companyId || '-' }}</el-descriptions-item>
          <el-descriptions-item label="version info">{{ license.versionInfo || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
      <div v-else class="status-section">
        <p class="hint-text">Submit a validation code below to activate the license.</p>
      </div>
    </el-card>

    <el-card class="license-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>host info</span>
        </div>
      </template>
      <div class="host-section">
        <el-descriptions :column="1" border class="arbore-descriptions">
          <el-descriptions-item label="host fingerprint">
            <span class="fingerprint-text">{{ license.hostFingerprint || 'loading...' }}</span>
            <el-button
              type="primary"
              size="small"
              @click="copyFingerprint"
              style="margin-left: 12px;"
            >
              copy
            </el-button>
          </el-descriptions-item>
        </el-descriptions>
        <p class="form-tip">Send the host fingerprint to support to obtain a validation code.</p>
      </div>
    </el-card>

    <el-card class="license-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>register license</span>
        </div>
      </template>
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="140px"
        label-position="left"
        class="register-form"
      >
        <el-form-item label="company id" prop="companyId">
          <el-input
            v-model="form.companyId"
            placeholder="Enter your company GUID"
            clearable
          />
        </el-form-item>
        <el-form-item label="validation code" prop="validationCode">
          <el-input
            v-model="form.validationCode"
            placeholder="Enter the validation code provided by support"
            type="password"
            show-password
            clearable
          />
        </el-form-item>
        <el-form-item label="company name" prop="companyName">
          <el-input
            v-model="form.companyName"
            placeholder="Enter your company name"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="submitting"
            @click="submitRegister"
          >
            register
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
// 许可证管理逻辑（License management logic）
// - fetchLicense:    拉取当前许可证与宿主机指纹
// - copyFingerprint: 一键复制硬件指纹
// - submitRegister:  提交注册表单到后端
import { ref, reactive, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const license = ref({
  registered: false,
  valid: false,
  errorCode: null,
  hostFingerprint: '',
  companyId: '',
  companyName: '',
  versionInfo: '',
})
const loading = ref(false)
const submitting = ref(false)
const formRef = ref(null)

const form = reactive({
  companyId: '',
  validationCode: '',
  companyName: '',
})

const formRules = {
  companyId:      [{ required: true, message: 'company id is required',      trigger: 'blur' }],
  validationCode: [{ required: true, message: 'validation code is required', trigger: 'blur' }],
  companyName:    [{ required: true, message: 'company name is required',    trigger: 'blur' }],
}

const apiBase = '/admin-api'
const licenseApiUrl    = () => `${apiBase}/api/v1/license`
const fingerprintApiUrl = () => `${apiBase}/api/v1/license/hardware-fingerprint`
const registerApiUrl   = () => `${apiBase}/api/v1/license/register`

async function fetchLicense() {
  loading.value = true
  try {
    const res = await axios.get(licenseApiUrl())
    license.value = {
      registered: !!res.data.registered,
      valid: !!res.data.valid,
      errorCode: res.data.errorCode || null,
      hostFingerprint: res.data.hostFingerprint || '',
      companyId: res.data.companyId || '',
      companyName: res.data.companyName || '',
      versionInfo: res.data.versionInfo || '',
    }
  } catch (err) {
    license.value.registered = false
    license.value.hostFingerprint = 'fetch failed'
    ElMessage.error('failed to load license: ' + (err.response?.data?.detail?.message || err.message))
  } finally {
    loading.value = false
  }
}

function copyFingerprint() {
  const text = license.value.hostFingerprint
  if (!text || text === 'loading...' || text === 'fetch failed') {
    ElMessage.warning('host fingerprint not available')
    return
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(
      () => ElMessage.success('copied to clipboard'),
      () => fallbackCopy(text),
    )
  } else {
    fallbackCopy(text)
  }
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
    ElMessage.success('copied to clipboard')
  } catch (e) {
    ElMessage.error('copy failed')
  }
  document.body.removeChild(ta)
}

async function submitRegister() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      const fd = new FormData()
      fd.append('companyId', form.companyId)
      fd.append('validationCode', form.validationCode)
      fd.append('companyName', form.companyName)
      await axios.post(registerApiUrl(), fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      ElMessage.success('license registered')
      form.companyId = ''
      form.validationCode = ''
      form.companyName = ''
      await fetchLicense()
    } catch (err) {
      const detail = err.response?.data?.detail
      const msg = (detail && (detail.message || detail)) || err.message
      ElMessage.error('registration failed: ' + msg)
    } finally {
      submitting.value = false
    }
  })
}

onMounted(() => {
  fetchLicense()
})
</script>

<style scoped>
/* License view - tuned to the global Catppuccin Mocha theme */
.license-view {
  padding: 0;
  font-family: var(--font-mono);
  color: var(--fg-text);
}

.page-header {
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

.license-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--fg-text);
  font-weight: 500;
  font-size: 12.5px;
  text-transform: lowercase;
  letter-spacing: 1px;
}

.status-section,
.host-section { color: var(--fg-text); }

.arbore-descriptions :deep(.el-descriptions__label) {
  background: var(--bg-base);
  color: var(--fg-muted);
  border-color: var(--border);
  font-weight: 500;
  font-size: 12px;
}
.arbore-descriptions :deep(.el-descriptions__content) {
  background: var(--bg-mantle);
  color: var(--fg-text);
  border-color: var(--border);
  font-size: 12.5px;
}
.arbore-descriptions :deep(.el-descriptions table) {
  border-color: var(--border) !important;
}

.fingerprint-text {
  font-family: var(--font-mono);
  color: var(--mocha-green);
  user-select: all;
  font-size: 12.5px;
}

.hint-text,
.form-tip {
  font-size: 12px;
  color: var(--fg-muted);
  margin: 0;
}
.form-tip { margin-top: 12px; }

.register-form :deep(.el-form-item__label) {
  color: var(--fg-muted);
  font-family: var(--font-mono);
  text-transform: lowercase;
  font-size: 12.5px;
}
</style>
