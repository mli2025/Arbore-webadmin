<template>
  <!--
    许可证管理视图 / License Management View

    中文说明：
    本组件用于展示宿主机硬件指纹、当前许可证状态，并提供一个简洁的注册表单，
    通过填入企业 ID 与校验码来激活 Arbore AI Host 的商业功能。页面强调
    “宿主机硬件指纹”这一概念，提醒用户在容器部署场景下需要挂载 machine-id。

    English description:
    This view is responsible for visualizing license status and guiding
    customers through the registration process.  It shows the host hardware
    fingerprint (derived from the machine‑id of the physical host) and
    offers a small form where the company identifier and validation code
    can be submitted to activate the platform.
  -->
  <div class="license-view">
    <div class="page-header">
      <div class="header-title">
        <h2>许可证管理</h2>
        <p class="header-desc">注册并验证 Arbore AI Host 许可证，硬件指纹为宿主机标识</p>
      </div>
    </div>

    <el-card class="license-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>注册状态</span>
          <el-tag v-if="license.registered" type="success" size="small">已注册</el-tag>
          <el-tag v-else type="info" size="small">未注册</el-tag>
        </div>
      </template>

      <div v-if="license.registered" class="status-section">
        <el-descriptions :column="1" border class="arbore-descriptions">
          <el-descriptions-item label="企业名称">{{ license.companyName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="企业ID">{{ license.companyId || '-' }}</el-descriptions-item>
          <el-descriptions-item label="版本信息">{{ license.versionInfo || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
      <div v-else class="status-section">
        <p class="hint-text">请完成下方注册表单并提交校验码以激活许可证。</p>
      </div>
    </el-card>

    <el-card class="license-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>主机信息</span>
        </div>
      </template>
      <div class="host-section">
        <el-descriptions :column="1" border class="arbore-descriptions">
          <el-descriptions-item label="主机标识（宿主机硬件指纹）">
            <span class="fingerprint-text">{{ license.hostFingerprint || '加载中...' }}</span>
            <el-button
              type="danger"
              size="small"
              plain
              @click="copyFingerprint"
              style="margin-left: 12px;"
            >
              复制
            </el-button>
          </el-descriptions-item>
        </el-descriptions>
        <p class="form-tip">将主机标识提供给客服以获取校验码。</p>
      </div>
    </el-card>

    <el-card class="license-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>注册许可证</span>
        </div>
      </template>
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="120px"
        label-position="left"
        class="register-form"
      >
        <el-form-item label="企业ID" prop="companyId">
          <el-input
            v-model="form.companyId"
            placeholder="Enter your company GUID"
            clearable
          />
        </el-form-item>
        <el-form-item label="校验码" prop="validationCode">
          <el-input
            v-model="form.validationCode"
            placeholder="Enter the validation code provided by support"
            type="password"
            show-password
            clearable
          />
        </el-form-item>
        <el-form-item label="企业名称" prop="companyName">
          <el-input
            v-model="form.companyName"
            placeholder="Enter your company name"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="danger"
            :loading="submitting"
            @click="submitRegister"
          >
            注册许可证
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
// 许可证管理逻辑（License management logic）
// - fetchLicense:  从后端拉取当前许可证与宿主机指纹信息；
// - copyFingerprint: 方便用户一键复制硬件指纹并发送给客服或销售；
// - submitRegister: 提交表单到后端进行许可证注册，并刷新展示状态。
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
  companyId: [{ required: true, message: '请输入企业ID', trigger: 'blur' }],
  validationCode: [{ required: true, message: '请输入校验码', trigger: 'blur' }],
  companyName: [{ required: true, message: '请输入企业名称', trigger: 'blur' }],
}

const apiBase = '/admin-api'
const licenseApiUrl = () => `${apiBase}/api/v1/license`
const fingerprintApiUrl = () => `${apiBase}/api/v1/license/hardware-fingerprint`
const registerApiUrl = () => `${apiBase}/api/v1/license/register`

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
    license.value.hostFingerprint = '获取失败'
    ElMessage.error('获取许可证信息失败: ' + (err.response?.data?.detail?.message || err.message))
  } finally {
    loading.value = false
  }
}

function copyFingerprint() {
  const text = license.value.hostFingerprint
  if (!text || text === '加载中...' || text === '获取失败') {
    ElMessage.warning('无可复制的主机标识')
    return
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(
      () => ElMessage.success('已复制到剪贴板'),
      () => fallbackCopy(text)
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
    ElMessage.success('已复制到剪贴板')
  } catch (e) {
    ElMessage.error('复制失败')
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
      ElMessage.success('许可证注册成功')
      form.companyId = ''
      form.validationCode = ''
      form.companyName = ''
      await fetchLicense()
    } catch (err) {
      const detail = err.response?.data?.detail
      const msg = (detail && (detail.message || detail)) || err.message
      ElMessage.error('注册失败: ' + msg)
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
.license-view {
  padding: 0;
}

.page-header {
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

.license-card {
  margin-bottom: 24px;
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 8px;
}

.license-card :deep(.el-card__header) {
  background: rgba(15, 23, 42, 0.5);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  padding: 16px 20px;
}

.license-card :deep(.el-card__body) {
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

.status-section,
.host-section {
  color: #f1f5f9;
}

.arbore-descriptions :deep(.el-descriptions__label) {
  background: rgba(15, 23, 42, 0.6);
  color: #94a3b8;
  border-color: rgba(148, 163, 184, 0.2);
}

.arbore-descriptions :deep(.el-descriptions__content) {
  background: rgba(30, 41, 59, 0.3);
  color: #f1f5f9;
  border-color: rgba(148, 163, 184, 0.2);
}

.fingerprint-text {
  font-family: monospace;
  color: #10b981;
  user-select: all;
}

.hint-text,
.form-tip {
  font-size: 14px;
  color: #94a3b8;
  margin: 0;
}

.form-tip {
  margin-top: 12px;
}

.register-form :deep(.el-form-item__label) {
  color: #94a3b8;
}

.register-form :deep(.el-input__wrapper) {
  background: rgba(15, 23, 42, 0.5);
  border-color: rgba(148, 163, 184, 0.2);
  box-shadow: none;
}

.register-form :deep(.el-input__wrapper:hover),
.register-form :deep(.el-input__wrapper.is-focus) {
  border-color: #10b981;
}

.register-form :deep(.el-input__inner) {
  color: #f1f5f9;
}
</style>
