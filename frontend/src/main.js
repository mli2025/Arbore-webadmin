// ============================================================================
// Arbore Web Admin 前端入口文件
// Arbore Web Admin Frontend Bootstrap Entry
//
// 本文件负责创建 Vue 应用实例、挂载全局 UI 组件库以及统一的品牌样式主题。
// 这里的初始化流程相对稳定，在后续版本演进中主要以“可配置”、“可扩展”为目标：
//   1) 如果未来有多语言支持，可在这里挂载 i18n 插件；
//   2) 如果需要全局状态管理，可在这里引入 Pinia 或 Vuex；
//   3) 如果要拓展更多全局指令 / 组件，同样建议在此集中注册。
//
// This file is the single bootstrap point for the Vue application.  It wires
// up Element Plus (the UI library), global icon components and the dark themed
// Arbore brand stylesheet, then mounts the root `App` component into the DOM.
// The code is intentionally small but heavily documented so that maintainers
// can quickly understand where to plug new capabilities into the frontend.
// ============================================================================

import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/arbore-theme.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'

const app = createApp(App)

// 注册 Element Plus 图标（Register all Element Plus icons globally）
// 这样在任意组件中都可以通过 <IconName /> 的方式直接使用，无需重复导入。
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 配置 Element Plus 主题色（Arbore 品牌色占位）
// Configure Element Plus theme (placeholder for Arbore brand palette).
// 目前仅简单启用组件库，后续如需精细化主题定制，可以在此对象中增加
// 全局尺寸、圆角、主色等参数。
app.use(ElementPlus, {
  // 可以在这里配置主题
})

app.mount('#app')

