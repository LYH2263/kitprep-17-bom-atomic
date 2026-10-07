<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

interface Leaf { ingredient_id: number; qty: number }
interface DishNode { dish_id: number; dish: string; code: string; children: Leaf[] }

const tree = ref<DishNode[]>([])
const ingredients = ref<any[]>([])
const saving = ref(false)
const msg = ref<{ kind: 'ok' | 'bad'; text: string } | null>(null)

async function load() {
  tree.value = await api('/bom/tree')
  ingredients.value = await api('/inventory')
}
onMounted(load)

function unitOf(id: number) { return ingredients.value.find(i => i.id === id)?.unit || '' }
function addLeaf(d: DishNode) {
  const used = new Set(d.children.map(c => c.ingredient_id))
  const pick = ingredients.value.find(i => !used.has(i.id))
  if (!pick) { msg.value = { kind: 'bad', text: '该菜品下原料已全部使用' }; return }
  d.children.push({ ingredient_id: pick.id, qty: 0 })
}
function removeLeaf(d: DishNode, idx: number) { d.children.splice(idx, 1) }

async function save() {
  msg.value = null
  const lines: { dish_id: number; ingredient_id: number; qty_per_portion: number }[] = []
  for (const d of tree.value) {
    const seen = new Set<number>()
    for (const c of d.children) {
      const qty = Number(c.qty)
      if (!Number.isFinite(qty) || qty < 0) {
        msg.value = { kind: 'bad', text: `「${d.dish}」存在空用量或负数用量，未保存任何内容` }
        return
      }
      if (seen.has(c.ingredient_id)) {
        msg.value = { kind: 'bad', text: `「${d.dish}」下同一原料重复，未保存任何内容` }
        return
      }
      seen.add(c.ingredient_id)
      lines.push({ dish_id: d.dish_id, ingredient_id: c.ingredient_id, qty_per_portion: qty })
    }
  }
  saving.value = true
  try {
    const res = await api<{ ok: boolean; count: number }>('/bom', {
      method: 'PUT', body: JSON.stringify({ lines }),
    })
    await load()
    msg.value = {
      kind: 'ok',
      text: `已保存 ${res.count} 条用量：定额树、当前有效备料单需求列与缺料贴已一起按新用量重写；账面结存未动，已存档旧单不变。`,
    }
  } catch (e: any) {
    let detail = String(e?.message || e)
    try { detail = JSON.parse(detail).detail || detail } catch { /* 保留原文 */ }
    // 后端整笔回滚：树、单、贴都停在保存前，重新拉取确认界面与库内一致
    await load()
    msg.value = { kind: 'bad', text: `保存被整笔退回：${detail}` }
  } finally {
    saving.value = false
  }
}
</script>
<template>
  <h1>BOM 树</h1>
  <p class="sub">菜品用料树 · 生产厨房口径 · 保存用量会同时重写当前有效备料单与缺料贴（不是出库，不动账面结存）</p>

  <div v-if="msg" :class="['badge', msg.kind === 'ok' ? 'badge-ok' : 'badge-bad']" style="display:block;max-width:640px;margin:0.5rem 0;white-space:normal">
    {{ msg.text }}
  </div>

  <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存用量' }}</button>

  <div class="kp-bom-tree" style="max-width:640px;margin-top:0.85rem">
    <h2>菜品 / BOM</h2>
    <div v-for="d in tree" :key="d.dish_id" class="kp-dish-node">
      <strong>{{ d.dish }}</strong>
      <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
      <ul style="list-style:none;padding-left:0">
        <li v-for="(c,i) in d.children" :key="i" style="display:flex;gap:0.5rem;align-items:center;margin:0.25rem 0">
          <select v-model.number="c.ingredient_id" style="min-width:120px">
            <option v-for="ing in ingredients" :key="ing.id" :value="ing.id">{{ ing.name }}</option>
          </select>
          <input v-model.number="c.qty" type="number" min="0" step="any"
                 style="width:90px" :aria-label="`${d.dish} 用量`" />
          <span style="min-width:36px">{{ unitOf(c.ingredient_id) }} / 份</span>
          <button class="btn" style="padding:0.1rem 0.5rem" @click="removeLeaf(d, i)">删除</button>
        </li>
      </ul>
      <button class="btn" style="padding:0.15rem 0.6rem" @click="addLeaf(d)">+ 原料叶子</button>
    </div>
  </div>
</template>
