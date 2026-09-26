<template>
  <section class="page" data-module="storage">
    <header class="page-head">
      <div>
        <h2>堆存计费管理</h2>
        <p class="page-desc">维护计费单，围绕计费单号、关联箱号、计费周期、堆存天数做登记、筛选与状态流转。金额由服务端统一口径核算，页面不自行计算。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记计费单</button>
        <button class="btn" type="button" @click="exportRows">导出堆存计费清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="filter-bar create-bar" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.name" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="createForm[field.name]" :placeholder="field.placeholder" />
      </label>
      <button class="btn" type="button" @click="previewFee">试算金额</button>
      <button class="btn primary" type="submit">提交登记</button>
      <button class="btn ghost" type="button" @click="closeCreate">取消</button>
      <span v-if="previewAmount" class="preview-amount">应收金额：{{ previewAmount }}</span>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted-text">已开票，不可变更</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无堆存计费数据，可先登记计费单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条堆存计费记录</span>
      <span v-if="noticeMessage" class="muted-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type ActionResult = {
  ok: boolean
  message: string
  entry?: Row | null
}

const ENDPOINT = '/api/storage'
const columns = ["计费单号", "关联箱号", "计费周期", "堆存天数", "计费标准", "应收金额", "客户名称", "计费状态"]
// 与服务端 ACTION_RULES 对齐：每个状态下一步可做的动作，已开票为终态
const nextActions: Record<string, string[]> = {
  "待核算": ["生成账单"],
  "已核算": ["确认对账"],
  "已对账": ["开具发票"],
  "已开票": [],
}
const createFields = [
  { name: "计费单号", label: "计费单号", placeholder: "如 STOR-0004" },
  { name: "关联箱号", label: "关联箱号", placeholder: "关联箱号" },
  { name: "计费周期", label: "计费周期", placeholder: "如 2026-09-01~2026-09-07" },
  { name: "堆存天数", label: "堆存天数", placeholder: "天数，不能为负" },
  { name: "计费标准", label: "计费标准", placeholder: "元/天" },
  { name: "客户名称", label: "客户名称", placeholder: "客户名称" },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const previewAmount = ref('')

const stats = computed(() => {
  const pending = rows.value.filter((row) => row['计费状态'] === '待核算').length
  const receivable = sumAmount(rows.value)
  const invoiced = sumAmount(rows.value.filter((row) => row['计费状态'] === '已开票'))
  return [
    { label: '待核算计费单', value: String(pending) },
    { label: '应收金额合计', value: receivable },
    { label: '已开票金额', value: invoiced },
  ]
})

function sumAmount(list: Row[]): string {
  // 仅做展示合计：金额本身由服务端算好，这里只把两位小数字符串相加
  const cents = list.reduce((acc, row) => acc + Math.round(Number(row['应收金额'] ?? 0) * 100), 0)
  return (cents / 100).toFixed(2)
}

function availableActions(row: Row): string[] {
  return nextActions[String(row['计费状态'] ?? row.status ?? '')] ?? []
}

function openCreate() {
  showCreate.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
}

function closeCreate() {
  showCreate.value = false
  createForm.value = {}
  previewAmount.value = ''
}

async function postAction(path: string, values: Record<string, unknown>): Promise<ActionResult> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return (await response.json()) as ActionResult
}

async function previewFee() {
  errorMessage.value = ''
  previewAmount.value = ''
  try {
    const result = await postAction(`${ENDPOINT}/preview`, createForm.value)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    previewAmount.value = String(result.entry?.['应收金额'] ?? '')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试算失败'
  }
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await postAction(ENDPOINT, createForm.value)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    noticeMessage.value = result.message
    closeCreate()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '计费单登记失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await postAction(`${ENDPOINT}/${row.id}/actions`, { action })
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    noticeMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存计费操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('计费单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存计费列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.create-bar {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.preview-amount {
  font-weight: 600;
}
.muted-text {
  color: var(--muted);
}
</style>
