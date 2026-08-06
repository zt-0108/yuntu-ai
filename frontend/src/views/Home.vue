<script setup lang="ts">
import axios from "axios";
import { computed, onUnmounted, reactive, ref } from "vue";
import { message } from "ant-design-vue";

import { generateTrip } from "../services/api";
import type { Itinerary, TripGenerationJobStatus, TripRequestPayload } from "../types";

const emit = defineEmits<{
  generated: [itinerary: Itinerary];
}>();

interface ChatMessage {
  id: number;
  role: "assistant" | "user";
  content: string;
}

const preferenceOptions = ["自然风景", "拍照", "美食", "古镇", "休闲", "亲子", "人文"];
const dietaryOptions = ["少辣", "不吃香菜", "不吃葱", "素食"];
const trainTypeOptions = ["G", "D", "C", "Z", "T", "K"] as const;
const quickPrompts = [
  "大理 3 天，想看日落和吃美食",
  "成都周末游，2 人预算 3000 元",
  "带父母去苏州，节奏轻松一点",
];

function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function addDays(dateText: string, amount: number): string {
  const date = new Date(`${dateText}T00:00:00`);
  if (Number.isNaN(date.getTime())) return dateText;
  date.setDate(date.getDate() + amount);
  return formatDate(date);
}

const today = new Date();
const formState = reactive({
  destination: "大理",
  departureCity: "",
  startDate: formatDate(today),
  endDate: addDays(formatDate(today), 2),
  travelers: 2,
  budget: 3200,
  hotelLevel: "舒适型",
  pace: "轻松",
  preferences: ["自然风景", "拍照", "美食"],
  dietaryPreferences: ["少辣"],
  preferredDeparturePeriod: "" as "" | "上午" | "下午" | "晚上",
  preferredTrainTypes: ["G", "D"] as Array<"G" | "D" | "C" | "Z" | "T" | "K">,
  seatPreference: "二等座" as "商务座" | "一等座" | "二等座" | "软卧" | "硬卧" | "硬座" | "无座",
  notes: "不想太早起床，希望安排一个适合看日落的地点。",
});

const chatInput = ref("");
const isSubmitting = ref(false);
const generationProgress = ref(0);
const generationStage = ref("准备生成");
const lastGenerationFailed = ref(false);
const detailsOpen = ref(false);
let generationController: AbortController | null = null;
let nextMessageId = 2;
const messages = ref<ChatMessage[]>([
  {
    id: 1,
    role: "assistant",
    content: "你好，我是云途旅行助手。告诉我想去哪里、玩几天，以及同行人和偏好，我会帮你整理成一份可执行的行程。",
  },
]);

const dayCount = computed(() => {
  const start = new Date(`${formState.startDate}T00:00:00`);
  const end = new Date(`${formState.endDate}T00:00:00`);
  const diff = end.getTime() - start.getTime();
  return Number.isNaN(diff) ? 0 : Math.max(Math.floor(diff / 86400000) + 1, 0);
});

const tripSummary = computed(() => [
  { icon: "📍", label: "目的地", value: formState.destination || "待确认" },
  ...(formState.departureCity ? [{ icon: "🚄", label: "往返车票", value: `${formState.departureCity} ⇄ ${formState.destination}` }] : []),
  { icon: "📅", label: "日期", value: `${formState.startDate} 至 ${formState.endDate}` },
  { icon: "👥", label: "同行", value: `${formState.travelers} 人 · ${dayCount.value} 天` },
  { icon: "💰", label: "预算", value: `¥${formState.budget.toLocaleString()}` },
]);

const generationStageLabels: Record<string, string> = {
  queued: "任务已排队",
  preparing: "正在准备旅行需求",
  retrieving_context: "正在检索目的地攻略",
  planning: "正在生成每日行程",
  assembling: "正在整理预算与路线",
  querying_rail: "正在查询往返车票",
  enriching_map: "正在补充地图信息",
  finalizing: "正在完成旅行方案",
  cancelling: "正在取消生成",
  cancelled: "生成已取消",
  completed: "旅行方案已完成",
  failed: "生成失败",
};

function handleGenerationProgress(job: TripGenerationJobStatus) {
  generationProgress.value = job.progress;
  generationStage.value = generationStageLabels[job.stage] || "正在规划旅程";
}

function parseRequest(text: string): string[] {
  const changed: string[] = [];
  const cities = ["北京", "上海", "广州", "深圳", "杭州", "苏州", "扬州", "南京", "成都", "重庆", "西安", "厦门", "青岛", "长沙", "武汉", "昆明", "大理", "丽江", "三亚", "桂林", "哈尔滨"];
  const routeMatch = text.match(new RegExp(`从?(${cities.join("|")})(?:出发)?(?:去|到|前往)(${cities.join("|")})`));
  if (routeMatch) {
    formState.departureCity = routeMatch[1];
    formState.destination = routeMatch[2];
    changed.push(`往返路线改为${routeMatch[1]}到${routeMatch[2]}`);
  }
  const city = routeMatch ? undefined : cities.find((item) => text.includes(item));
  if (city && city !== formState.destination) {
    formState.destination = city;
    changed.push(`目的地改为${city}`);
  }

  const dateMatches = text.match(/20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?/g);
  if (dateMatches?.length) {
    const normalize = (value: string) => value.replace(/[/.年月]/g, "-").replace(/日$/, "").replace(/-$/, "").split("-").map((part, index) => index === 0 ? part : part.padStart(2, "0")).join("-");
    formState.startDate = normalize(dateMatches[0]);
    if (dateMatches[1]) formState.endDate = normalize(dateMatches[1]);
    changed.push("已更新出行日期");
  }

  const days = text.match(/(\d+)\s*天/);
  if (days) {
    const count = Math.max(1, Number(days[1]));
    formState.endDate = addDays(formState.startDate, count - 1);
    changed.push(`行程安排为${count}天`);
  }

  const people = text.match(/(\d+)\s*(?:人|位)/);
  if (people) {
    formState.travelers = Math.max(1, Number(people[1]));
    changed.push(`同行人数为${formState.travelers}人`);
  }

  const budget = text.match(/(?:预算|人均)[^\d]{0,4}(\d+(?:\.\d+)?)\s*(万|千|k|K)?/);
  if (budget) {
    const multiplier = budget[2] === "万" ? 10000 : ["千", "k", "K"].includes(budget[2] || "") ? 1000 : 1;
    formState.budget = Math.round(Number(budget[1]) * multiplier);
    changed.push(`预算调整为¥${formState.budget.toLocaleString()}`);
  }

  const matchedPreferences = preferenceOptions.filter((item) => text.includes(item));
  if (text.includes("日落") && !matchedPreferences.includes("拍照")) matchedPreferences.push("拍照");
  if (matchedPreferences.length) {
    formState.preferences = Array.from(new Set([...formState.preferences, ...matchedPreferences]));
    changed.push(`已记住${matchedPreferences.join("、")}偏好`);
  }

  if (/轻松|慢一点|不赶/.test(text)) formState.pace = "轻松";
  if (/紧凑|多安排|特种兵/.test(text)) formState.pace = "紧凑";
  if (/经济|省钱/.test(text)) formState.hotelLevel = "经济型";
  if (/高档|豪华|品质酒店/.test(text)) formState.hotelLevel = "高档型";

  formState.notes = text;
  return changed;
}

function sendMessage(text = chatInput.value) {
  const value = text.trim();
  if (!value) return;
  messages.value.push({ id: nextMessageId++, role: "user", content: value });
  const changed = parseRequest(value);
  const reply = changed.length
    ? `好的，${changed.join("，")}。我已经同步到右侧行程卡片，你可以继续补充要求，或直接让我生成完整方案。`
    : "我记下了。你还可以补充出行日期、人数、预算或偏好；信息确认后，我就可以开始生成行程。";
  messages.value.push({ id: nextMessageId++, role: "assistant", content: reply });
  chatInput.value = "";
}

async function handleSubmit() {
  if (isSubmitting.value) return;
  if (!formState.destination || dayCount.value <= 0) {
    message.warning("请先确认目的地和有效的出行日期。");
    return;
  }

  const payload: TripRequestPayload = {
    destination: formState.destination,
    start_date: formState.startDate,
    end_date: formState.endDate,
    travelers: formState.travelers,
    budget: formState.budget,
    preferences: formState.preferences,
    pace: formState.pace,
    dietary_preferences: formState.dietaryPreferences,
    hotel_level: formState.hotelLevel,
    special_notes: formState.notes,
    departure_city: formState.departureCity || null,
    preferred_departure_period: formState.preferredDeparturePeriod || null,
    preferred_train_types: formState.preferredTrainTypes,
    seat_preference: formState.seatPreference,
  };

  isSubmitting.value = true;
  lastGenerationFailed.value = false;
  generationProgress.value = 0;
  generationStage.value = generationStageLabels.queued;
  generationController = new AbortController();
  messages.value.push({ id: nextMessageId++, role: "assistant", content: `正在为你规划${formState.destination}${dayCount.value}天行程，我会综合路线、预算、住宿与天气建议，请稍等。` });
  try {
    const itinerary = await generateTrip(
      payload,
      handleGenerationProgress,
      generationController.signal,
    );
    message.success("旅行方案已生成");
    emit("generated", itinerary);
  } catch (error) {
    console.error(error);
    if (error instanceof DOMException && error.name === "AbortError") {
      messages.value.push({ id: nextMessageId++, role: "assistant", content: "本次行程生成已取消，你可以调整需求后重新生成。" });
      message.info("已取消行程生成");
      return;
    }
    lastGenerationFailed.value = true;
    messages.value.push({ id: nextMessageId++, role: "assistant", content: "这次生成没有成功，请检查服务连接后再试一次。你的旅行需求已经保留。" });
    if (
      (axios.isAxiosError(error) && error.code === "ECONNABORTED")
      || (error instanceof Error && error.message.includes("超时"))
    ) {
      message.error("生成超时，请稍后再试。");
    } else {
      message.error("生成失败，请检查后端服务状态。");
    }
  } finally {
    isSubmitting.value = false;
    generationController = null;
  }
}

function handleCancelGeneration() {
  generationStage.value = generationStageLabels.cancelling;
  generationController?.abort();
}

onUnmounted(() => {
  generationController?.abort();
});
</script>

<template>
  <section class="assistant-page">
    <div class="assistant-panel">
      <div class="assistant-panel__header">
        <div class="assistant-avatar">云</div>
        <div>
          <div class="assistant-name">云途旅行助手</div>
          <div class="assistant-status"><span></span> 在线 · 随时帮你规划</div>
        </div>
      </div>

      <div class="conversation" aria-live="polite">
        <div v-for="item in messages" :key="item.id" :class="['message-row', `message-row--${item.role}`]">
          <div v-if="item.role === 'assistant'" class="message-avatar">云</div>
          <div class="message-bubble">{{ item.content }}</div>
        </div>
      </div>

      <div class="quick-prompts">
        <button v-for="prompt in quickPrompts" :key="prompt" @click="sendMessage(prompt)">{{ prompt }}</button>
      </div>

      <div class="composer">
        <textarea
          v-model="chatInput"
          rows="3"
          placeholder="例如：10 月想和朋友去成都玩 4 天，预算 5000，喜欢美食，不要太赶……"
          @keydown.enter.exact.prevent="sendMessage()"
        ></textarea>
        <div class="composer__footer">
          <span>按 Enter 发送，Shift + Enter 换行</span>
          <button :disabled="!chatInput.trim()" aria-label="发送旅行需求" @click="sendMessage()">➤</button>
        </div>
      </div>
    </div>

    <aside class="trip-panel">
      <div class="trip-panel__eyebrow">YOUR TRIP</div>
      <div class="trip-panel__title-row">
        <div>
          <h2>{{ formState.destination || "我的旅行" }}</h2>
          <p>根据对话实时整理，可随时修改</p>
        </div>
        <div class="trip-panel__days">{{ dayCount }}<small>天</small></div>
      </div>

      <div class="summary-list">
        <div v-for="item in tripSummary" :key="item.label" class="summary-item">
          <span class="summary-item__icon">{{ item.icon }}</span>
          <div><small>{{ item.label }}</small><strong>{{ item.value }}</strong></div>
        </div>
      </div>

      <div class="preference-block">
        <div class="block-label">旅行偏好</div>
        <div class="tag-list">
          <button
            v-for="item in preferenceOptions"
            :key="item"
            :class="{ active: formState.preferences.includes(item) }"
            @click="formState.preferences = formState.preferences.includes(item) ? formState.preferences.filter((value) => value !== item) : [...formState.preferences, item]"
          >{{ item }}</button>
        </div>
      </div>

      <button class="details-toggle" @click="detailsOpen = !detailsOpen">
        <span>详细设置</span><span>{{ detailsOpen ? "收起 −" : "展开 +" }}</span>
      </button>

      <div v-if="detailsOpen" class="details-form">
        <label>目的地<input v-model="formState.destination" /></label>
        <label>铁路出发城市（选填）<input v-model="formState.departureCity" placeholder="例如：上海" /></label>
        <div class="details-form__row">
          <label>开始日期<input v-model="formState.startDate" type="date" /></label>
          <label>结束日期<input v-model="formState.endDate" type="date" /></label>
        </div>
        <div class="details-form__row">
          <label>人数<input v-model.number="formState.travelers" type="number" min="1" /></label>
          <label>总预算<input v-model.number="formState.budget" type="number" min="0" /></label>
        </div>
        <div class="details-form__row">
          <label>行程节奏
            <select v-model="formState.pace"><option>轻松</option><option>适中</option><option>紧凑</option></select>
          </label>
          <label>住宿标准
            <select v-model="formState.hotelLevel"><option>经济型</option><option>舒适型</option><option>高档型</option></select>
          </label>
        </div>
        <div class="block-label">饮食要求</div>
        <div class="tag-list tag-list--small">
          <button
            v-for="item in dietaryOptions"
            :key="item"
            :class="{ active: formState.dietaryPreferences.includes(item) }"
            @click="formState.dietaryPreferences = formState.dietaryPreferences.includes(item) ? formState.dietaryPreferences.filter((value) => value !== item) : [...formState.dietaryPreferences, item]"
          >{{ item }}</button>
        </div>
        <div class="details-form__row">
          <label>列车出发时段
            <select v-model="formState.preferredDeparturePeriod"><option value="">不限</option><option>上午</option><option>下午</option><option>晚上</option></select>
          </label>
          <label>优先席别
            <select v-model="formState.seatPreference"><option>商务座</option><option>一等座</option><option>二等座</option><option>软卧</option><option>硬卧</option><option>硬座</option><option>无座</option></select>
          </label>
        </div>
        <div class="block-label">优先车次类型</div>
        <div class="tag-list tag-list--small">
          <button
            v-for="item in trainTypeOptions"
            :key="item"
            :class="{ active: formState.preferredTrainTypes.includes(item) }"
            @click="formState.preferredTrainTypes = formState.preferredTrainTypes.includes(item) ? formState.preferredTrainTypes.filter((value) => value !== item) : [...formState.preferredTrainTypes, item]"
          >{{ item }}</button>
        </div>
      </div>

      <div v-if="isSubmitting" class="generation-progress" aria-live="polite">
        <div class="generation-progress__label">
          <span>{{ generationStage }}</span>
          <strong>{{ generationProgress }}%</strong>
        </div>
        <div class="generation-progress__track">
          <span :style="{ width: `${generationProgress}%` }"></span>
        </div>
        <button class="generation-progress__cancel" @click="handleCancelGeneration">
          取消生成
        </button>
      </div>

      <button class="generate-button" :disabled="isSubmitting" @click="handleSubmit">
        <span>{{ isSubmitting ? "正在规划旅程…" : lastGenerationFailed ? "重新生成旅行方案" : "生成我的旅行方案" }}</span><span v-if="!isSubmitting">→</span>
      </button>
      <div class="privacy-note">🔒 仅查询公开车次信息，不收集 12306 账号、密码或乘车人身份信息</div>
    </aside>
  </section>
</template>

<style scoped>
.assistant-page { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(340px, .85fr); gap: 22px; align-items: start; }
.assistant-panel, .trip-panel { border: 1px solid rgba(117, 128, 156, .13); border-radius: 26px; background: rgba(255,255,255,.94); box-shadow: 0 24px 60px rgba(61, 75, 111, .12); backdrop-filter: blur(16px); }
.assistant-panel { min-height: 680px; display: flex; flex-direction: column; overflow: hidden; }
.assistant-panel__header { display: flex; align-items: center; gap: 12px; padding: 20px 24px; border-bottom: 1px solid #edf0f5; }
.assistant-avatar, .message-avatar { display: grid; place-items: center; flex: 0 0 auto; border-radius: 16px; color: #fff; font-weight: 800; background: linear-gradient(145deg,#5777e8,#8359d1); box-shadow: 0 8px 20px rgba(96,91,205,.24); }
.assistant-avatar { width: 44px; height: 44px; font-size: 18px; }
.assistant-name { color: #263248; font-size: 16px; font-weight: 800; }
.assistant-status { margin-top: 4px; color: #8a93a3; font-size: 12px; }
.assistant-status span { display: inline-block; width: 7px; height: 7px; margin-right: 5px; border-radius: 50%; background: #34c98f; }
.conversation { flex: 1; display: flex; flex-direction: column; gap: 18px; max-height: 390px; overflow: auto; padding: 26px 24px; background: linear-gradient(180deg,#fbfcff,#fff); }
.message-row { display: flex; gap: 10px; align-items: flex-end; }
.message-row--user { justify-content: flex-end; }
.message-avatar { width: 32px; height: 32px; border-radius: 11px; font-size: 12px; }
.message-bubble { max-width: 78%; padding: 14px 16px; border-radius: 6px 18px 18px; color: #4a566b; background: #f0f3f9; line-height: 1.72; font-size: 14px; }
.message-row--user .message-bubble { border-radius: 18px 6px 18px 18px; color: #fff; background: linear-gradient(135deg,#667eea,#7967d8); }
.quick-prompts { display: flex; gap: 8px; padding: 4px 24px 14px; overflow-x: auto; }
.quick-prompts button, .tag-list button { border: 1px solid #e3e7ef; border-radius: 999px; background: #fff; color: #687386; cursor: pointer; white-space: nowrap; transition: .2s; }
.quick-prompts button { padding: 8px 12px; font-size: 12px; }
.quick-prompts button:hover, .tag-list button:hover { border-color: #7181df; color: #5968c6; }
.composer { margin: 0 20px 20px; padding: 12px 14px 9px; border: 1px solid #dfe4ed; border-radius: 18px; background: #fff; box-shadow: 0 8px 24px rgba(62,76,112,.07); }
.composer:focus-within { border-color: #7a83db; box-shadow: 0 0 0 3px rgba(106,116,215,.1); }
.composer textarea { width: 100%; min-height: 68px; resize: none; border: 0; outline: 0; color: #344054; font: inherit; line-height: 1.6; }
.composer__footer { display: flex; justify-content: space-between; align-items: center; color: #a0a7b4; font-size: 11px; }
.composer__footer button { width: 35px; height: 35px; border: 0; border-radius: 12px; color: #fff; background: linear-gradient(135deg,#6479e5,#8262d1); cursor: pointer; }
.composer__footer button:disabled { opacity: .35; cursor: not-allowed; }
.trip-panel { padding: 26px; }
.trip-panel__eyebrow { color: #7869d5; font-size: 11px; font-weight: 900; letter-spacing: .18em; }
.trip-panel__title-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 8px 0 20px; border-bottom: 1px solid #edf0f5; }
.trip-panel h2 { margin: 0; color: #253047; font-size: 28px; }
.trip-panel p { margin: 5px 0 0; color: #939baa; font-size: 12px; }
.trip-panel__days { color: #6474d9; font-size: 34px; font-weight: 800; }
.trip-panel__days small { margin-left: 3px; font-size: 13px; }
.summary-list { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 18px 0; }
.summary-item { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 12px; border-radius: 14px; background: #f7f8fc; }
.summary-item__icon { display: grid; place-items: center; width: 32px; height: 32px; flex: 0 0 auto; border-radius: 10px; background: #fff; }
.summary-item small, .summary-item strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.summary-item small { color: #9aa2b0; font-size: 10px; }
.summary-item strong { margin-top: 3px; color: #465166; font-size: 12px; }
.block-label { margin: 15px 0 9px; color: #667085; font-size: 12px; font-weight: 800; }
.tag-list { display: flex; flex-wrap: wrap; gap: 7px; }
.tag-list button { padding: 7px 11px; font-size: 12px; }
.tag-list button.active { border-color: #6e79d7; color: #5966c2; background: #eef0ff; }
.details-toggle { display: flex; justify-content: space-between; width: 100%; margin: 20px 0 0; padding: 13px 0; border: 0; border-top: 1px solid #edf0f5; color: #697386; background: transparent; cursor: pointer; font-weight: 700; }
.details-form { display: grid; gap: 11px; padding: 13px; border-radius: 16px; background: #f8f9fc; }
.details-form__row { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.details-form label { display: grid; gap: 5px; color: #7b8494; font-size: 11px; }
.details-form input, .details-form select { min-width: 0; width: 100%; height: 36px; padding: 0 9px; border: 1px solid #e0e4ec; border-radius: 9px; color: #344054; background: #fff; outline: none; }
.generation-progress { margin-top: 18px; padding: 12px 14px; border-radius: 13px; background: #f4f5ff; }
.generation-progress__label { display: flex; justify-content: space-between; gap: 12px; color: #687386; font-size: 11px; }
.generation-progress__label strong { color: #6474d9; }
.generation-progress__track { height: 7px; margin-top: 9px; overflow: hidden; border-radius: 999px; background: #dfe3f5; }
.generation-progress__track span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg,#657ce7,#8261d0); transition: width .35s ease; }
.generation-progress__cancel { display: block; margin: 10px 0 0 auto; padding: 0; border: 0; color: #747d9a; background: transparent; cursor: pointer; font-size: 11px; }
.generation-progress__cancel:hover { color: #d35f6d; }
.generate-button { display: flex; justify-content: space-between; align-items: center; width: 100%; margin-top: 22px; padding: 15px 19px; border: 0; border-radius: 15px; color: #fff; background: linear-gradient(135deg,#657ce7,#8261d0); box-shadow: 0 13px 28px rgba(97,102,205,.24); cursor: pointer; font-weight: 800; }
.generate-button:disabled { opacity: .65; cursor: wait; }
.privacy-note { margin-top: 12px; color: #a0a7b4; text-align: center; font-size: 10px; }
@media (max-width: 980px) { .assistant-page { grid-template-columns: 1fr; } .assistant-panel { min-height: 620px; } }
@media (max-width: 560px) { .assistant-panel, .trip-panel { border-radius: 20px; } .assistant-panel__header, .conversation { padding-left: 16px; padding-right: 16px; } .quick-prompts { padding-left: 16px; padding-right: 16px; } .composer { margin-left: 12px; margin-right: 12px; } .summary-list { grid-template-columns: 1fr; } .message-bubble { max-width: 86%; } }
</style>
