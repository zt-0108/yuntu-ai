<script setup lang="ts">
import { message } from "ant-design-vue";
import { computed, onMounted, ref, watch } from "vue";

import { deleteTrip, getTripDetail, listTrips } from "../services/api";
import type { Itinerary, TripSummaryItem } from "../types";

const props = defineProps<{ active: boolean }>();
const emit = defineEmits<{ openTrip: [itinerary: Itinerary] }>();

const loading = ref(false);
const items = ref<TripSummaryItem[]>([]);
const deletingTripId = ref("");
const query = ref("");

const filteredItems = computed(() => {
  const keyword = query.value.trim().toLowerCase();
  if (!keyword) return items.value;
  return items.value.filter((item) => `${item.destination} ${item.summary}`.toLowerCase().includes(keyword));
});

function formatDate(value?: string | null) {
  if (!value) return "日期未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(date);
}

function destinationMark(destination: string) {
  return destination.trim().slice(0, 1) || "旅";
}

async function loadTrips() {
  loading.value = true;
  try {
    const response = await listTrips();
    items.value = response.items;
  } catch (error) {
    console.error(error);
    message.error("旅行收藏加载失败，请检查服务连接。");
  } finally {
    loading.value = false;
  }
}

async function openTrip(tripId: string) {
  try {
    const response = await getTripDetail(tripId);
    emit("openTrip", response.itinerary);
    message.success("行程已打开");
  } catch (error) {
    console.error(error);
    message.error("暂时无法读取这份行程。");
  }
}

async function removeTrip(tripId: string) {
  if (!window.confirm("确定移除这份旅行收藏吗？此操作无法撤销。")) return;
  deletingTripId.value = tripId;
  try {
    await deleteTrip(tripId);
    items.value = items.value.filter((item) => item.trip_id !== tripId);
    message.success("已从旅行收藏中移除");
  } catch (error) {
    console.error(error);
    message.error("移除失败，请稍后重试。");
  } finally {
    deletingTripId.value = "";
  }
}

onMounted(() => { if (props.active) void loadTrips(); });
watch(() => props.active, (active) => { if (active) void loadTrips(); });
</script>

<template>
  <section class="journey-library">
    <header class="library-header">
      <div class="library-header__copy">
        <div class="library-header__eyebrow">MY JOURNEYS</div>
        <h2>旅行收藏夹</h2>
        <p>每一次出发都有迹可循，随时回来继续调整你的旅行计划。</p>
      </div>
      <div class="library-header__stats">
        <strong>{{ items.length }}</strong><span>份旅程</span>
      </div>
    </header>

    <div class="library-tools">
      <label class="search-box">
        <span>⌕</span>
        <input v-model="query" placeholder="搜索目的地或行程关键词" />
      </label>
      <button class="refresh-button" :disabled="loading" @click="loadTrips">
        {{ loading ? "同步中…" : "↻ 同步收藏" }}
      </button>
    </div>

    <div v-if="loading" class="library-state">
      <div class="state-orbit"><span></span></div>
      <strong>正在整理你的旅行收藏</strong>
      <p>稍等片刻，美好的计划马上回来。</p>
    </div>
    <div v-else-if="items.length === 0" class="library-state">
      <div class="state-icon">🧳</div>
      <strong>收藏夹还是空的</strong>
      <p>生成旅行方案后点击“收藏行程”，它就会出现在这里。</p>
    </div>
    <div v-else-if="filteredItems.length === 0" class="library-state library-state--compact">
      <div class="state-icon">🔎</div>
      <strong>没有找到匹配的旅程</strong>
      <p>换一个目的地或关键词试试看。</p>
    </div>

    <div v-else class="journey-grid">
      <article v-for="(item, index) in filteredItems" :key="item.trip_id" class="journey-card">
        <div :class="['journey-card__cover', `journey-card__cover--${index % 4}`]">
          <span class="journey-card__mark">{{ destinationMark(item.destination) }}</span>
          <span class="journey-card__badge">已收藏</span>
          <div class="journey-card__destination">{{ item.destination }}</div>
        </div>
        <div class="journey-card__body">
          <div class="journey-card__date">最近更新 · {{ formatDate(item.updated_at) }}</div>
          <p>{{ item.summary || "一份等待再次出发的旅行计划。" }}</p>
          <div class="journey-card__footer">
            <button class="open-button" @click="openTrip(item.trip_id)">继续规划 <span>→</span></button>
            <button class="remove-button" :disabled="deletingTripId === item.trip_id" aria-label="删除行程" @click="removeTrip(item.trip_id)">
              {{ deletingTripId === item.trip_id ? "…" : "删除" }}
            </button>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.journey-library { display: grid; gap: 18px; }
.library-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 30px 34px; overflow: hidden; border-radius: 26px; color: #fff; background: linear-gradient(125deg,#415fae,#6f65cc 60%,#865ebc); box-shadow: 0 22px 55px rgba(67,77,148,.22); }
.library-header__eyebrow { margin-bottom: 7px; color: rgba(255,255,255,.65); font-size: 10px; font-weight: 900; letter-spacing: .22em; }
.library-header h2 { margin: 0; font-size: 30px; }
.library-header p { margin: 8px 0 0; color: rgba(255,255,255,.72); font-size: 13px; }
.library-header__stats { display: grid; flex: 0 0 auto; place-items: center; width: 92px; height: 92px; border: 1px solid rgba(255,255,255,.22); border-radius: 50%; background: rgba(255,255,255,.11); backdrop-filter: blur(8px); }
.library-header__stats strong { margin-bottom: -18px; font-size: 30px; }
.library-header__stats span { font-size: 11px; color: rgba(255,255,255,.72); }
.library-tools { display: flex; justify-content: space-between; gap: 12px; padding: 14px; border: 1px solid rgba(117,128,156,.12); border-radius: 20px; background: rgba(255,255,255,.9); }
.search-box { display: flex; align-items: center; flex: 1; gap: 9px; max-width: 480px; padding: 0 14px; border-radius: 12px; background: #f5f7fb; color: #8992a3; }
.search-box input { width: 100%; height: 42px; border: 0; outline: 0; color: #344054; background: transparent; }
.refresh-button { border: 0; border-radius: 12px; padding: 0 17px; color: #5d68c7; background: #eef0ff; cursor: pointer; font-weight: 800; }
.refresh-button:disabled { opacity: .6; }
.journey-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(280px,1fr)); gap: 18px; }
.journey-card { overflow: hidden; border: 1px solid rgba(117,128,156,.12); border-radius: 23px; background: rgba(255,255,255,.94); box-shadow: 0 18px 42px rgba(61,75,111,.09); transition: transform .2s, box-shadow .2s; }
.journey-card:hover { transform: translateY(-3px); box-shadow: 0 24px 48px rgba(61,75,111,.14); }
.journey-card__cover { position: relative; min-height: 145px; padding: 22px; overflow: hidden; color: #fff; background: linear-gradient(135deg,#5876b9,#6d62c6); }
.journey-card__cover::after { content:""; position:absolute; width:150px; height:150px; right:-35px; top:-45px; border-radius:50%; border:28px solid rgba(255,255,255,.1); }
.journey-card__cover--1 { background:linear-gradient(135deg,#398b91,#56a386); }
.journey-card__cover--2 { background:linear-gradient(135deg,#b16c54,#cf9368); }
.journey-card__cover--3 { background:linear-gradient(135deg,#526f9e,#6c8daf); }
.journey-card__mark { display:grid; place-items:center; width:42px; height:42px; border-radius:14px; background:rgba(255,255,255,.18); font-weight:900; backdrop-filter:blur(6px); }
.journey-card__badge { position:absolute; top:20px; right:20px; z-index:1; padding:5px 9px; border-radius:999px; background:rgba(255,255,255,.16); font-size:10px; }
.journey-card__destination { position:absolute; left:22px; bottom:19px; font-size:27px; font-weight:900; }
.journey-card__body { padding:19px 20px 18px; }
.journey-card__date { color:#9aa2b0; font-size:11px; }
.journey-card p { min-height:52px; margin:10px 0 17px; display:-webkit-box; overflow:hidden; color:#596579; line-height:1.65; font-size:13px; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.journey-card__footer { display:flex; gap:9px; }
.open-button { display:flex; justify-content:space-between; flex:1; padding:11px 14px; border:0; border-radius:11px; color:#fff; background:linear-gradient(135deg,#657ae2,#7765d0); cursor:pointer; font-weight:800; }
.remove-button { padding:0 12px; border:0; border-radius:11px; color:#a05f65; background:#fff1f2; cursor:pointer; }
.library-state { display:grid; place-items:center; min-height:330px; padding:45px; border:1px solid rgba(117,128,156,.12); border-radius:24px; background:rgba(255,255,255,.92); color:#344054; text-align:center; }
.library-state--compact { min-height:220px; }
.library-state strong { margin-top:12px; font-size:18px; }
.library-state p { margin:8px 0 0; color:#8a93a3; }
.state-icon { font-size:42px; }
.state-orbit { width:42px; height:42px; padding:5px; border:2px solid #e4e7fb; border-top-color:#6b77d6; border-radius:50%; animation:spin .8s linear infinite; }
.state-orbit span { display:block; width:100%; height:100%; border-radius:50%; background:#eef0ff; }
@keyframes spin { to { transform:rotate(360deg); } }
@media(max-width:640px){.library-header{padding:24px}.library-header__stats{width:74px;height:74px}.library-header h2{font-size:25px}.library-header p{display:none}.library-tools{flex-direction:column}.search-box{max-width:none}.refresh-button{min-height:42px}}
</style>
